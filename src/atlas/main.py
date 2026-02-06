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

from .binance_public import BinancePublic
from .yahoo_data import YahooData
from .engines_binance_mentor import BinanceMentorEngine
from .engines_binomo_trading import BinomoTradingEngine
from .commands_admin import register_admin_commands

BR_TZ = pytz.timezone("America/Sao_Paulo")


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _hhmm(now: datetime) -> str:
    return now.strftime("%H:%M")


def _in_times(now: datetime, times: list[str]) -> bool:
    return _hhmm(now) in set(times or [])


class AtlasClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = AtlasTree(self)


class AtlasTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        admin_ch = int(getattr(config, "CANAL_ADMIN_BOT", 0) or 0)
        if admin_ch <= 0:
            return True

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

    timeout = aiohttp.ClientTimeout(total=25)
    connector = aiohttp.TCPConnector(limit=60)
    session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    logger = DiscordLogger(
        client=client,
        logs_channel_id=int(getattr(config, "CANAL_LOGS", 0) or 0),
        level=settings.log_level,
    )
    notifier = DiscordNotifier(client)
    tg = TelegramNotifier(session, settings.telegram_token, settings.telegram_chat_id)

    LOCK = asyncio.Lock()

    # ── NEWS ─────────────────────────────────────────────────────────────
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

    news_member_times = list(getattr(config, "NEWS_MEMBER_TIMES", ["09:00"]))
    news_invest_times = list(getattr(config, "NEWS_INVEST_TIMES", ["09:00", "18:00"]))

    # ── BINANCE MENTOR (INVESTIMENTO) ────────────────────────────────────
    binance = BinancePublic(session)
    mentor = BinanceMentorEngine()

    binance_symbols = list(getattr(config, "BINANCE_SYMBOLS", []))
    binance_member_times = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]))
    binance_member_days = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2) or 2)
    binance_invest_times = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]))

    ch_binance_member = int(getattr(config, "CANAL_BINANCE_MEMBRO", 0) or 0)
    ch_binance_invest = int(getattr(config, "CANAL_BINANCE_INVESTIDOR", 0) or 0)

    # ── BINOMO TRADING ───────────────────────────────────────────────────
    yahoo = YahooData(session)
    trader = BinomoTradingEngine()

    binomo_tickers = list(getattr(config, "BINOMO_TICKERS", []))
    trading_member_times = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]))
    invest_on_minute = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0) or 0)
    invest_max = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3) or 3)
    invest_tfs = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]))

    ch_trade_member = int(getattr(config, "CANAL_TRADING_MEMBRO", 0) or 0)
    ch_trade_invest = int(getattr(config, "CANAL_TRADING_INVESTIDOR", 0) or 0)

    # ── SYNC + COMMANDS ─────────────────────────────────────────────────
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
        # testa tudo em TODOS os canais (mesmo fora do horário)
        try:
            async with LOCK:
                await news_job.run_both()

                # Binance mentor: manda 1 pick em ambos
                pick = await mentor.scan(binance, binance_symbols)
                emb_m = mentor.build_embed(pick, tier="membro")
                emb_i = mentor.build_embed(pick, tier="investidor")
                if ch_binance_member:
                    await notifier.send_embed(ch_binance_member, emb_m)
                if ch_binance_invest:
                    await notifier.send_embed(ch_binance_invest, emb_i)

                # Trading: membro 1 sinal M5; invest até 3 (M5+M15)
                e_m = await trader.scan(yahoo, binomo_tickers, "5m", 1)
                if ch_trade_member:
                    await notifier.send_embed(ch_trade_member, trader.build_embed(e_m, tier="membro"))

                pool = []
                for tf in invest_tfs:
                    pool += await trader.scan(yahoo, binomo_tickers, tf, invest_max)
                pool.sort(key=lambda x: x.score, reverse=True)
                pool = pool[:invest_max]
                if ch_trade_invest:
                    await notifier.send_embed(ch_trade_invest, trader.build_embed(pool, tier="investidor"))

            return "OK (news + binance mentor + binomo trading)"
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
        await logger.info("Loops: NEWS + BINANCE_MENTOR + BINOMO_TRADING armados.")

    # ───────────────────────── LOOPS ─────────────────────────
    async def loop_news():
        last = None
        while not stop_event.is_set():
            try:
                now = _now_brt()
                key = now.strftime("%Y-%m-%d %H:%M")
                if key != last:
                    last = key
                    if _in_times(now, news_member_times) or _in_times(now, news_invest_times):
                        async with LOCK:
                            await news_job.run_both()
            except Exception as e:
                await logger.error(f"NEWS LOOP error: {e}")
            await asyncio.sleep(30)

    async def loop_binance_mentor():
        last_key = None
        while not stop_event.is_set():
            try:
                now = _now_brt()
                key = now.strftime("%Y-%m-%d %H:%M")
                if key != last_key:
                    last_key = key

                    # Premium 2x/dia
                    if _in_times(now, binance_invest_times):
                        async with LOCK:
                            pick = await mentor.scan(binance, binance_symbols)
                            emb = mentor.build_embed(pick, tier="investidor")
                            if ch_binance_invest:
                                await notifier.send_embed(ch_binance_invest, emb)
                            await logger.info(f"BINANCE INVEST sent {key} pick={'OK' if pick else 'NONE'}")

                    # Membro a cada 2 dias, em horário fixo
                    if _in_times(now, binance_member_times):
                        # cooldown 2 dias (em memória; se reiniciar o bot, ele pode reenviar)
                        if state.cooldown_ok("binance_member_2days", binance_member_days * 24 * 3600):
                            async with LOCK:
                                pick = await mentor.scan(binance, binance_symbols)
                                emb = mentor.build_embed(pick, tier="membro")
                                if ch_binance_member:
                                    await notifier.send_embed(ch_binance_member, emb)
                                await logger.info(f"BINANCE MEMBRO sent {key} pick={'OK' if pick else 'NONE'}")
            except Exception as e:
                await logger.error(f"BINANCE LOOP error: {e}")
            await asyncio.sleep(30)

    async def loop_binomo_trading():
        last_member_day = None
        last_invest_hour = None
        while not stop_event.is_set():
            try:
                now = _now_brt()

                # mercado fechado (simplificado): fim de semana
                is_weekend = datetime.utcnow().weekday() >= 5

                # MEMBRO: 1x/dia (M5)
                day_key = now.strftime("%Y-%m-%d")
                if day_key != last_member_day and _in_times(now, trading_member_times):
                    last_member_day = day_key
                    if is_weekend:
                        await logger.info(f"TRADING MEMBRO skip (mercado fechado) {day_key}")
                    else:
                        async with LOCK:
                            entries = await trader.scan(yahoo, binomo_tickers, "5m", 1)
                            if entries and ch_trade_member:
                                await notifier.send_embed(ch_trade_member, trader.build_embed(entries, "membro"))
                                await logger.info(f"TRADING MEMBRO sent {now.strftime('%Y-%m-%d %H:%M')}")
                            else:
                                await logger.info(f"TRADING MEMBRO sem entradas {now.strftime('%Y-%m-%d %H:%M')}")

                # INVESTIDOR: 1x/h no minuto 00 → 3 entradas (M5+M15)
                hour_key = now.strftime("%Y-%m-%d %H")
                if now.minute == invest_on_minute and hour_key != last_invest_hour:
                    last_invest_hour = hour_key
                    if is_weekend:
                        await logger.info(f"TRADING INVEST skip (mercado fechado) {hour_key}")
                    else:
                        async with LOCK:
                            pool = []
                            for tf in invest_tfs:
                                pool += await trader.scan(yahoo, binomo_tickers, tf, invest_max)
                            pool.sort(key=lambda x: x.score, reverse=True)
                            pool = pool[:invest_max]
                            if pool and ch_trade_invest:
                                await notifier.send_embed(ch_trade_invest, trader.build_embed(pool, "investidor"))
                                await logger.info(f"TRADING INVEST sent {hour_key}: n={len(pool)}")
                            else:
                                await logger.info(f"TRADING INVEST sem entradas {hour_key}")
            except Exception as e:
                await logger.error(f"TRADING LOOP error: {e}")
            await asyncio.sleep(20)

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    async with client:
        asyncio.create_task(loop_news())
        asyncio.create_task(loop_binance_mentor())
        asyncio.create_task(loop_binomo_trading())
        await client.start(settings.discord_token)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
