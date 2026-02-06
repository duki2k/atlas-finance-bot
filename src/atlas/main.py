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


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _should_run_at_times(now: datetime, times: list[str]) -> bool:
    # times exemplo: ["09:00", "18:00"]
    hhmm = now.strftime("%H:%M")
    return hhmm in set(times or [])


class AtlasClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = AtlasTree(self)


class AtlasTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        admin_ch = int(getattr(config, "CANAL_ADMIN_BOT", 0) or 0)
        if admin_ch <= 0:
            return True

        # bloqueia DM
        if interaction.guild is None:
            with contextlib.suppress(Exception):
                if interaction.response.is_done():
                    await interaction.followup.send("⛔ Use comandos apenas no servidor.", ephemeral=True)
                else:
                    await interaction.response.send_message("⛔ Use comandos apenas no servidor.", ephemeral=True)
            return False

        if interaction.channel_id != admin_ch:
            with contextlib.suppress(Exception):
                msg = f"⛔ Use comandos apenas em <#{admin_ch}>."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            return False

        return True


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
    newsroom = NewsroomEngine(feeds_en=feeds_en)

    news_job = NewsJob(
        state=state,
        logger=logger,
        notifier=notifier,
        tg=tg,
        engine=newsroom,
        channel_member_id=int(getattr(config, "CANAL_NEWS_MEMBRO", 0) or 0),
        channel_invest_id=int(getattr(config, "CANAL_NEWS_INVESTIDOR", 0) or 0),
        max_member=int(getattr(config, "NEWS_MAX_ITEMS_MEMBER", 4) or 4),
        max_invest=int(getattr(config, "NEWS_MAX_ITEMS_INVEST", 7) or 7),
        telegram_enabled=bool(getattr(config, "TELEGRAM_ENABLED", False) and getattr(config, "TELEGRAM_SEND_NEWS", True)),
        discord_invite=str(getattr(config, "DISCORD_INVITE_LINK", "") or "").strip(),
    )

    member_times = list(getattr(config, "NEWS_MEMBER_TIMES", ["09:00"]))
    invest_times = list(getattr(config, "NEWS_INVEST_TIMES", ["09:00", "18:00"]))

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
            await news_job.run_both()
            return "OK (news membro+invest)"
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
        await logger.info(f"NEWS schedule: membro={member_times} invest={invest_times}")

    async def news_loop():
        last_key = None
        while not stop_event.is_set():
            try:
                now = _now_brt()
                minute_key = now.strftime("%Y-%m-%d %H:%M")
                if minute_key != last_key:
                    last_key = minute_key

                    # Se bateu algum horário (membro OU investidor), manda para os dois canais,
                    # mas o INVESTIDOR tem 2 horários no dia e o MEMBRO só 1.
                    if _should_run_at_times(now, member_times) or _should_run_at_times(now, invest_times):
                        await news_job.run_both()

            except Exception as e:
                await logger.error(f"NEWS LOOP error: {e}")
            await asyncio.sleep(30)

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    async with client:
        asyncio.create_task(news_loop())
        await client.start(settings.discord_token)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
