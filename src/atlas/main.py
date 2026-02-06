from __future__ import annotations
import asyncio
import contextlib
import signal
from datetime import datetime

import aiohttp
import discord
import pytz

import config

from .settings import load_settings
from .state import State
from .observability import DiscordLogger
from .notifier_discord import DiscordNotifier
from .notifier_telegram import TelegramNotifier
from .engines_newsroom import NewsroomEngine
from .jobs_news import NewsJob
from .commands_admin import register_admin_commands

BR_TZ = pytz.timezone("America/Sao_Paulo")


class AtlasClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)


async def run():
    settings = load_settings()
    intents = discord.Intents.default()
    client = AtlasClient(intents=intents)

    state = State()

    http_timeout = aiohttp.ClientTimeout(total=25)
    connector = aiohttp.TCPConnector(limit=60)
    session = aiohttp.ClientSession(timeout=http_timeout, connector=connector)

    logger = DiscordLogger(
        client=client,
        logs_channel_id=int(getattr(config, "CANAL_LOGS", 0) or 0),
        level=settings.log_level,
    )
    notifier = DiscordNotifier(client)
    tg = TelegramNotifier(session, settings.telegram_token, settings.telegram_chat_id)

    feeds_en = list(getattr(config, "NEWS_RSS_FEEDS_EN", []))
    max_items = int(getattr(config, "NEWS_MAX_ITEMS_EACH", 6) or 6)
    newsroom = NewsroomEngine(feeds_en=feeds_en, max_items=max_items)

    news_job = NewsJob(
        state=state,
        logger=logger,
        notifier=notifier,
        tg=tg,
        engine=newsroom,
        channel_id=int(getattr(config, "CANAL_NEWS_CRIPTO", 0) or 0),
        telegram_enabled=bool(getattr(config, "TELEGRAM_ENABLED", False) and getattr(config, "TELEGRAM_SEND_NEWS", True)),
        discord_invite=str(getattr(config, "DISCORD_INVITE_LINK", "") or "").strip(),
    )

    async def sync_commands():
        try:
            if settings.guild_id:
                guild = discord.Object(id=int(settings.guild_id))
                client.tree.copy_global_to(guild=guild)
                synced = await client.tree.sync(guild=guild)
                await logger.info(f"SYNC GUILD {settings.guild_id}: {len(synced)} cmds -> {[c.name for c in synced]}")
            else:
                synced = await client.tree.sync()
                await logger.info(f"SYNC GLOBAL: {len(synced)} cmds -> {[c.name for c in synced]}")
        except Exception as e:
            await logger.error(f"Falha SYNC: {e}")

    async def force_all():
        try:
            await news_job.run()
            return "OK (news)"
        except Exception as e:
            await logger.error(f"FORCE_ALL falhou: {e}")
            return f"FAIL ({e})"

    register_admin_commands(client.tree, state, logger, sync_commands, force_all, settings)

    stop_event = asyncio.Event()

    async def shutdown(reason: str):
        await logger.warn(f"Shutdown: {reason}")
        stop_event.set()
        with contextlib.suppress(Exception):
            await client.close()
        with contextlib.suppress(Exception):
            if not session.closed:
                await session.close()

    def install_signal_handlers(loop: asyncio.AbstractEventLoop):
        def _handler(sig_name: str):
            asyncio.create_task(shutdown(sig_name))
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _handler, sig.name)

    @client.event
    async def on_ready():
        await logger.info(f"READY: {client.user} (sync={settings.sync_commands})")
        if settings.sync_commands:
            await sync_commands()
        await logger.info("Job NEWS armado (v6).")

    async def news_loop():
        every = int(getattr(config, "NEWS_EVERY_MINUTES", 30) or 30)
        last_key = None
        while not stop_event.is_set():
            try:
                now = datetime.now(BR_TZ)
                minute_key = now.strftime("%Y-%m-%d %H:%M")
                if minute_key != last_key and (now.minute % every == 0):
                    last_key = minute_key
                    await news_job.run()
            except Exception as e:
                await logger.error(f"NEWS LOOP error: {e}")
            await asyncio.sleep(60)

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    async with client:
        asyncio.create_task(news_loop())
        await client.start(settings.discord_token)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
