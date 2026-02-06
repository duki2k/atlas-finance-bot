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


def _cfg_int(name: str, default: int = 0) -> int:
    return int(getattr(config, name, default) or default)


def _cfg_str(name: str, default: str = "") -> str:
    return str(getattr(config, name, default) or default).strip()


class AtlasClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = AtlasTree(self)


class AtlasTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        admin_ch = _cfg_int("CANAL_ADMIN_BOT", 0) or _cfg_int("CANAL_ADMIN", 0)
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
        logs_channel_id=_cfg_int("CANAL_LOGS", 0),
        level=settings.log_level,
    )
    notifier = DiscordNotifier(client)
    tg = TelegramNotifier(session, settings.telegram_token, settings.telegram_chat_id)

    LOCK = asyncio.Lock()

    # ── NEWS ─────────────────────────────────────────────────────────────
    feeds_en = list(getattr(config, "NEWS_RSS_FEEDS_EN", []))
    newsroom = NewsroomEngine(feeds_en=feeds_en)

    news_member_ch = _cfg_int("CANAL_NEWS_MEMBRO", 0) or _cfg_int("CANAL_NEWS_CRIPTO", 0)
    news_invest_ch = _cfg_int("CANAL_NEWS_INVESTIDOR", 0)

    news_job = NewsJob(
        state=state,
        logger=logger,
        notifier=notifier,
        tg=tg,
        engine=newsroom,
        channel_member_id=news_member_ch,
        channel_invest_id=news_invest_ch,
        max_member=_cfg_int("NEWS_MAX_ITEMS_MEMBER", 4),
        max_invest=_cfg_int("NEWS_MAX_ITEMS_INVEST", 7),
        telegram_enabled=bool(getattr(config, "TELEGRAM_ENABLED", False) and getattr(config, "TELEGRAM_SEND_NEWS", True)),
        discord_invite=_cfg_str("DISCORD_INVITE_LINK", ""),
    )

    news_member_times = list(getattr(config, "NEWS_MEMBER_TIMES", ["09:00"]))
    news_invest_times = list(getattr(config, "NEWS_INVEST_TIMES", ["09:00", "18:00"]))

    # ── BINANCE MENTOR (INVESTIMENTO) ────────────────────────────────────
    binance = BinancePublic(session)
    mentor = BinanceMentorEngine()

    binance_symbols = list(getattr(config, "BINANCE_SYMBOLS", []))
    binance_member_times = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]))
    binance_member_every_days = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2) or 2)
    binance_invest_times = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]))

    ch_binance_member = _cfg_int("CANAL_BINANCE_MEMBRO", 0)
    ch_binance_invest = _cfg_int("CANAL_BINANCE_INVESTIDOR", 0)

    # ── BINOMO TRADING ───────────────────────────────────────────────────
    yahoo = YahooData(session)
    trader = BinomoTradingEngine()

    binomo_tickers = list(getattr(config, "BINOMO_TICKERS", []))

    trading_member_times = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]))
    invest_on_minute = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0) or 0)
    invest_max = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3) or 3)
    invest_tfs = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]))

    ch_trade_member = _cfg_int("CANAL_TRADING_MEMBRO", 0) or _cfg_int("CANAL_BINOMO_MEMBRO", 0)
    ch_trade_invest = _cfg_int("CANAL_TRADING_INVESTIDOR", 0) or _cfg_int("CANAL_BINOMO_INVESTIDOR", 0)

    trade_cd_min = int(getattr(config, "TRADING_TICKER_COOLDOWN_MINUTES_INVEST", 180) or 180)
    trade_cd_sec = trade_cd_min * 60

    # ── helpers ─────────────────────────────────────────────────────────
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

    async def _send(channel_id: int, embed: discord.Embed) -> tuple[bool, str]:
        if not channel_id:
            return False, "SKIP(channel_id=0)"
        try:
            await notifier.send_embed(int(channel_id), embed)
            return True, "OK"
        except Exception as e:
            return False, f"FAIL({e})"

    def _pick_top_with_cooldown(entries, tier_key: str, limit: int, ignore_cooldown: bool) -> list:
        picked = []
        used = set()
        for x in sorted(entries, key=lambda z: z.score, reverse=True):
            if x.ticker in used:
                continue
            if not ignore_cooldown:
                cd_key = f"cd:{tier_key}:{x.ticker}"
                if not state.cooldown_ok(cd_key, trade_cd_sec):
                    continue
            used.add(x.ticker)
            picked.append(x)
            if len(picked) >= limit:
                break
        return picked

    # ── FORCE ALL (relatório real) ───────────────────────────────────────
    async def force_all():
        report = []

        async with LOCK:
            # NEWS
            try:
                await news_job.run_both()
                report.append(f"NEWS ✅ member={news_member_ch or 0} invest={news_invest_ch or 0}")
            except Exception as e:
                report.append(f"NEWS ❌ {e}")

            # BINANCE mentor
            try:
                pick = await mentor.scan(binance, binance_symbols)
                emb_m = mentor.build_embed(pick, tier="membro")
                emb_i = mentor.build_embed(pick, tier="investidor")

                okm, em = await _send(ch_binance_member, emb_m)
                oki, ei = await _send(ch_binance_invest, emb_i)

                report.append(f"BINANCE_MEMBRO {okm} ({em}) -> {ch_binance_member}")
                report.append(f"BINANCE_INVEST {oki} ({ei}) -> {ch_binance_invest}")
            except Exception as e:
                report.append(f"BINANCE ❌ {e}")

            # TRADING membro (M5 1x)
            try:
                e_m = await trader.scan(yahoo, binomo_tickers, "5m", 1)
                emb = trader.build_embed(e_m, tier="membro")
                ok, err = await _send(ch_trade_member, emb)
                report.append(f"TRADING_MEMBRO {ok} ({err}) -> {ch_trade_member}")
            except Exception as e:
                report.append(f"TRADING_MEMBRO ❌ {e}")

            # TRADING invest (3 entradas M5/M15, ignorando cooldown no force_all)
            try:
                pool = []
                for tf in invest_tfs:
                    pool += await trader.scan(yahoo, binomo_tickers, tf, invest_max)

                picked = _pick_top_with_cooldown(pool, "inv", invest_max, ignore_cooldown=True)
                emb = trader.build_embed(picked, tier="investidor")
                ok, err = await _send(ch_trade_invest, emb)
                report.append(f"TRADING_INVEST {ok} ({err}) -> {ch_trade_invest} n={len(picked)}")
            except Exception as e:
                report.append(f"TRADING_INVEST ❌ {e}")

        # loga relatório completo
        await logger.info("FORCE_ALL: " + " | ".join(report))
        return "\n".join(report)

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

    # ───────────────────────── LOOPS ─────────────────────────
    async def loop_binance_mentor():
        last_member_day = None
        last_invest_key = None

        while not stop_event.is_set():
            try:
                now = _now_brt()
                hhmm = _hhmm(now)

                # investidor 2x/dia
                key = now.strftime("%Y-%m-%d %H:%M")
                if hhmm in set(binance_invest_times) and key != last_invest_key:
                    last_invest_key = key
                    async with LOCK:
                        pick = await mentor.scan(binance, binance_symbols)
                        emb = mentor.build_embed(pick, tier="investidor")
                        ok, err = await _send(ch_binance_invest, emb)
                    await logger.info(f"BINANCE_INVEST {key} -> {ok} {err}")

                # membro 1x a cada 2 dias (por calendário, não depende de restart)
                if hhmm in set(binance_member_times):
                    day = now.strftime("%Y-%m-%d")
                    if day != last_member_day:
                        # regra “a cada 2 dias”: usa ordinal do dia
                        if (now.date().toordinal() % binance_member_every_days) == 0:
                            last_member_day = day
                            async with LOCK:
                                pick = await mentor.scan(binance, binance_symbols)
                                emb = mentor.build_embed(pick, tier="membro")
                                ok, err = await _send(ch_binance_member, emb)
                            await logger.info(f"BINANCE_MEMBRO {day} -> {ok} {err}")

            except Exception as e:
                await logger.error(f"BINANCE LOOP error: {e}")
            await asyncio.sleep(20)

    async def loop_binomo_trading():
        last_member_day = None
        last_invest_hour = None

        while not stop_event.is_set():
            try:
                now = _now_brt()
                is_weekend = datetime.utcnow().weekday() >= 5

                # MEMBRO: 1x/dia em M5
                hhmm = _hhmm(now)
                day = now.strftime("%Y-%m-%d")
                if hhmm in set(trading_member_times) and day != last_member_day:
                    last_member_day = day
                    if is_weekend:
                        await logger.info(f"TRADING_MEMBRO skip (fim de semana) {day}")
                    else:
                        async with LOCK:
                            e_m = await trader.scan(yahoo, binomo_tickers, "5m", 1)
                            emb = trader.build_embed(e_m, tier="membro")
                            ok, err = await _send(ch_trade_member, emb)
                        await logger.info(f"TRADING_MEMBRO {day} -> {ok} {err}")

                # INVESTIDOR: 1x/h no minuto X, 3 entradas M5/M15 com cooldown por ticker
                hour_key = now.strftime("%Y-%m-%d %H")
                if now.minute == invest_on_minute and hour_key != last_invest_hour:
                    last_invest_hour = hour_key
                    if is_weekend:
                        await logger.info(f"TRADING_INVEST skip (fim de semana) {hour_key}")
                    else:
                        async with LOCK:
                            pool = []
                            for tf in invest_tfs:
                                pool += await trader.scan(yahoo, binomo_tickers, tf, invest_max)

                            picked = _pick_top_with_cooldown(pool, "inv", invest_max, ignore_cooldown=False)
                            emb = trader.build_embed(picked, tier="investidor")
                            ok, err = await _send(ch_trade_invest, emb)

                        await logger.info(
                            f"TRADING_INVEST {hour_key} -> {ok} {err} n={len(picked)} cd={trade_cd_min}m"
                        )

            except Exception as e:
                await logger.error(f"TRADING LOOP error: {e}")
            await asyncio.sleep(15)

    async def loop_news():
        last_key = None
        while not stop_event.is_set():
            try:
                now = _now_brt()
                key = now.strftime("%Y-%m-%d %H:%M")
                if key != last_key:
                    last_key = key
                    if _in_times(now, news_member_times) or _in_times(now, news_invest_times):
                        async with LOCK:
                            await news_job.run_both()
            except Exception as e:
                await logger.error(f"NEWS LOOP error: {e}")
            await asyncio.sleep(30)

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
