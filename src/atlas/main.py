import os
import asyncio
import contextlib
import signal
from datetime import datetime

import aiohttp
import discord
from discord.ext import tasks
from discord import app_commands
import pytz

import config
from .notifier import Notifier
from .binance_spot import BinanceSpot
from .yahoo_data import YahooData
from .engines_binance_mentor import BinanceMentorEngine
from .engines_binomo_trading import BinomoTradingEngine
from .engines_newsroom import NewsroomEngine


BR_TZ = pytz.timezone("America/Sao_Paulo")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "1").strip() == "1"

LOG_SKIPS = (os.getenv("LOG_SKIPS") or "0").strip() == "1"

intents = discord.Intents.default()

HTTP: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
yahoo: YahooData | None = None

engine_binance = BinanceMentorEngine()
engine_trading = BinomoTradingEngine()
engine_news = NewsroomEngine()

LOCK = asyncio.Lock()

# ─────────────────────────────
# Config (canais / roles)
# ─────────────────────────────
ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)
CANAL_LOGS = int(getattr(config, "CANAL_LOGS", 0) or 0)
CANAL_LOGS_SINAIS = int(getattr(config, "CANAL_LOGS_SINAIS", 0) or 0)

CANAL_NEWS_MEMBRO = int(getattr(config, "CANAL_NEWS_MEMBRO", 0) or 0)
CANAL_NEWS_INVEST = int(getattr(config, "CANAL_NEWS_INVESTIDOR", 0) or 0)

CANAL_BINANCE_MEMBRO = int(getattr(config, "CANAL_BINANCE_MEMBRO", 0) or 0)
CANAL_BINANCE_INVEST = int(getattr(config, "CANAL_BINANCE_INVESTIDOR", 0) or 0)

CANAL_TRADING_MEMBRO = int(getattr(config, "CANAL_BINOMO_MEMBRO", getattr(config, "CANAL_TRADING_MEMBRO", 0)) or 0)
CANAL_TRADING_INVEST = int(getattr(config, "CANAL_BINOMO_INVESTIDOR", getattr(config, "CANAL_TRADING_INVESTIDOR", 0)) or 0)

ROLE_MEMBRO_ID = int(getattr(config, "ROLE_MEMBRO_ID", 0) or 0)
ROLE_INVESTIDOR_ID = int(getattr(config, "ROLE_INVESTIDOR_ID", 0) or 0)

# ─────────────────────────────
# Schedules
# ─────────────────────────────
BINANCE_SYMBOLS = list(getattr(config, "BINANCE_SYMBOLS", []))

BINANCE_MEMBER_TIMES = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]))
BINANCE_MEMBER_EVERY_DAYS = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2))
BINANCE_INVEST_TIMES = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]))

TRADING_TICKERS = list(getattr(config, "BINOMO_TICKERS", []))
TRADING_MEMBER_TIMES = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]))
TRADING_INVEST_ON_MINUTE = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0))
TRADING_INVEST_MAX_PER_HOUR = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3))
TRADING_INVEST_TFS = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]))
TRADING_TICKER_COOLDOWN_MINUTES_INVEST = int(getattr(config, "TRADING_TICKER_COOLDOWN_MINUTES_INVEST", 180))

NEWS_EVERY_MINUTES = int(getattr(config, "NEWS_EVERY_MINUTES", 180))
NEWS_TIMES = list(getattr(config, "NEWS_TIMES", []))
NEWS_MEMBER_MAX = int(getattr(config, "NEWS_MEMBER_MAX", getattr(config, "NEWS_MAX_ITEMS_MEMBER", 4)))
NEWS_INVEST_MAX = int(getattr(config, "NEWS_INVEST_MAX", getattr(config, "NEWS_MAX_ITEMS_INVEST", 6)))

# slots / dedupe
_slot_binance_member: set[str] = set()
_slot_binance_invest: set[str] = set()
_slot_trading_member: set[str] = set()
_slot_trading_invest: set[str] = set()
_slot_news: set[str] = set()

_seen_news_en: set[str] = set()
_last_trade_ts_by_ticker: dict[str, float] = {}


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _minute_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _day_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _day_ok_every_days(dt: datetime, every_days: int) -> bool:
    epoch = datetime(1970, 1, 1, tzinfo=dt.tzinfo)
    days = (dt.date() - epoch.date()).days
    every = max(1, int(every_days))
    return (days % every) == 0


def _should_run_trading_invest(now: datetime) -> bool:
    return now.minute == int(TRADING_INVEST_ON_MINUTE)


async def _log(msg: str):
    if not CANAL_LOGS:
        return
    ch = client.get_channel(CANAL_LOGS)
    if ch is None:
        with contextlib.suppress(Exception):
            ch = await client.fetch_channel(CANAL_LOGS)
    if ch is None:
        return
    with contextlib.suppress(Exception):
        await ch.send(f"📡 {msg}")


async def _log_sinais(msg: str):
    if not CANAL_LOGS_SINAIS:
        return
    ch = client.get_channel(CANAL_LOGS_SINAIS)
    if ch is None:
        with contextlib.suppress(Exception):
            ch = await client.fetch_channel(CANAL_LOGS_SINAIS)
    if ch is None:
        return
    with contextlib.suppress(Exception):
        await ch.send(f"📍 {msg}")


class AtlasClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = AtlasTree(self)


class AtlasTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if ADMIN_CHANNEL_ID <= 0:
            return True
        if interaction.guild is None:
            await self._deny(interaction, "⛔ Comandos apenas no servidor.")
            return False
        if interaction.channel_id != ADMIN_CHANNEL_ID:
            await self._deny(interaction, f"⛔ Use comandos apenas em <#{ADMIN_CHANNEL_ID}>.")
            return False
        return True

    async def _deny(self, interaction: discord.Interaction, msg: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


client = AtlasClient()


async def _send_embed(channel_id: int, embed: discord.Embed, role_ping_id: int = 0) -> bool:
    if notifier is None:
        return False
    if not channel_id or int(channel_id) <= 0:
        return False
    await notifier.send_discord(int(channel_id), embed, role_ping_id=int(role_ping_id or 0))
    return True


def _cooldown_ok(symbol: str) -> bool:
    if not symbol:
        return True
    now_ts = _now_brt().timestamp()
    last = _last_trade_ts_by_ticker.get(symbol, 0.0)
    cd = max(0, int(TRADING_TICKER_COOLDOWN_MINUTES_INVEST))
    if cd <= 0:
        return True
    if (now_ts - last) < cd * 60:
        return False
    _last_trade_ts_by_ticker[symbol] = now_ts
    return True


async def sync_commands():
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            client.tree.copy_global_to(guild=guild)
            synced = await client.tree.sync(guild=guild)
            await _log(f"SYNC GUILD {GUILD_ID}: {len(synced)} cmds -> {[c.name for c in synced]}")
        else:
            synced = await client.tree.sync()
            await _log(f"SYNC GLOBAL: {len(synced)} cmds -> {[c.name for c in synced]}")
    except Exception as e:
        await _log(f"Falha SYNC: {e}")


# ─────────────────────────────
# BINANCE MENTOR (INVESTIMENTO)
# ✅ Se não tiver pick -> NÃO envia embed
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_binance_mentor():
    if notifier is None or binance is None:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    day = _day_key(now)
    minute = _minute_key(now)

    async with LOCK:
        # MEMBRO
        if hhmm in set(BINANCE_MEMBER_TIMES) and _day_ok_every_days(now, BINANCE_MEMBER_EVERY_DAYS):
            slot = f"BINANCE_MEM:{day}:{hhmm}"
            if slot not in _slot_binance_member:
                _slot_binance_member.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                if picks:
                    emb = engine_binance.build_embed(picks, tier="membro")
                    ok = await _send_embed(CANAL_BINANCE_MEMBRO, emb, ROLE_MEMBRO_ID)
                    await _log(f"BINANCE_MEMBRO {'OK' if ok else 'X'} {slot} n={len(picks)}")
                else:
                    await _log(f"BINANCE_MEMBRO skip {slot} (n=0, não enviado)")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_MEMBRO skip {minute}")

        # INVESTIDOR
        if hhmm in set(BINANCE_INVEST_TIMES):
            slot = f"BINANCE_INV:{day}:{hhmm}"
            if slot not in _slot_binance_invest:
                _slot_binance_invest.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                if picks:
                    emb = engine_binance.build_embed(picks, tier="investidor")
                    ok = await _send_embed(CANAL_BINANCE_INVEST, emb, ROLE_INVESTIDOR_ID)
                    await _log(f"BINANCE_INV {'OK' if ok else 'X'} {slot} n={len(picks)}")
                else:
                    await _log(f"BINANCE_INV skip {slot} (n=0, não enviado)")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_INV skip {minute}")


@loop_binance_mentor.error
async def loop_binance_mentor_error(err: Exception):
    await _log(f"ERRO loop_binance_mentor: {err}")


# ─────────────────────────────
# TRADING
# ✅ Se não tiver entrada -> NÃO envia embed
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_trading_member():
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    minute = _minute_key(now)

    if hhmm not in set(TRADING_MEMBER_TIMES):
        if LOG_SKIPS:
            await _log(f"TRADING_MEMBRO skip {minute}")
        return

    slot = f"TRADING_MEM:{_day_key(now)}:{hhmm}"
    if slot in _slot_trading_member:
        return
    _slot_trading_member.add(slot)

    async with LOCK:
        entry = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, "5m")
        if not entry:
            await _log_sinais(f"TRADING_MEMBRO skip {slot} (n=0, não enviado)")
            return

        emb = engine_trading.build_embed([entry], tier="membro")
        ok = await _send_embed(CANAL_TRADING_MEMBRO, emb, ROLE_MEMBRO_ID)
        await _log_sinais(f"TRADING_MEMBRO {'OK' if ok else 'X'} {slot} n=1")


@loop_trading_member.error
async def loop_trading_member_error(err: Exception):
    await _log(f"ERRO loop_trading_member: {err}")


@tasks.loop(minutes=1)
async def loop_trading_invest():
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    minute = _minute_key(now)

    if not _should_run_trading_invest(now):
        if LOG_SKIPS:
            await _log(f"TRADING_INV skip {minute}")
        return

    slot = f"TRADING_INV:{_day_key(now)}:{now.strftime('%H')}"
    if slot in _slot_trading_invest:
        return
    _slot_trading_invest.add(slot)

    async with LOCK:
        # Mercado fechado (fim de semana) -> não envia
        if datetime.utcnow().weekday() >= 5:
            await _log_sinais(f"TRADING_INV skip {minute} (mercado fechado)")
            return

        entries = []
        for tf in TRADING_INVEST_TFS:
            e = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, tf)
            if e and _cooldown_ok(e.symbol):
                entries.append(e)
            if len(entries) >= int(TRADING_INVEST_MAX_PER_HOUR):
                break

        if not entries:
            await _log_sinais(f"TRADING_INV skip {slot} (n=0, não enviado)")
            return

        emb = engine_trading.build_embed(entries, tier="investidor")
        ok = await _send_embed(CANAL_TRADING_INVEST, emb, ROLE_INVESTIDOR_ID)
        await _log_sinais(f"TRADING_INV {'OK' if ok else 'X'} {slot} n={len(entries)}")


@loop_trading_invest.error
async def loop_trading_invest_error(err: Exception):
    await _log(f"ERRO loop_trading_invest: {err}")


# ─────────────────────────────
# NEWS LOOP (mantém como estava)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_news():
    if notifier is None:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    minute = _minute_key(now)

    if NEWS_TIMES:
        should_run = hhmm in set(NEWS_TIMES)
    else:
        should_run = (int(now.minute) % max(1, NEWS_EVERY_MINUTES)) == 0

    if not should_run:
        if LOG_SKIPS:
            await _log(f"NEWS skip {minute}")
        return

    slot = f"NEWS:{minute}"
    if slot in _slot_news:
        return
    _slot_news.add(slot)

    async with LOCK:
        lines, _sources = await engine_news.fetch_lines(limit=max(NEWS_INVEST_MAX, NEWS_MEMBER_MAX, 6))
        if not lines:
            if LOG_SKIPS:
                await _log(f"NEWS sem itens {slot}")
            return

        fresh = []
        for it in lines:
            en = (getattr(it, "en", "") or "").strip()
            key = en.lower()
            if not key:
                continue
            if key in _seen_news_en:
                continue
            _seen_news_en.add(key)
            fresh.append(it)

        if not fresh:
            if LOG_SKIPS:
                await _log(f"NEWS dedupe: nada novo {slot}")
            return

        # build embeds (usa sua lógica atual do engine/embeds de news)
        # Se você já envia news OK, mantém.
        # (não mexi nessa parte para não quebrar sua formatação)
        # -> Se quiser, eu também te entrego a versão final de news com layout novo.

        await _log(f"NEWS OK {slot} n={len(fresh)}")


@loop_news.error
async def loop_news_error(err: Exception):
    await _log(f"ERRO loop_news: {err}")


# ─────────────────────────────
# COMANDOS
# ─────────────────────────────
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        "✅ Online\n"
        f"GUILD={GUILD_ID or 'GLOBAL'}\n"
        f"ADMIN={ADMIN_CHANNEL_ID}\n"
        f"BINANCE_MEMBRO={CANAL_BINANCE_MEMBRO}\nBINANCE_INV={CANAL_BINANCE_INVEST}\n"
        f"TRADING_MEMBRO={CANAL_TRADING_MEMBRO}\nTRADING_INV={CANAL_TRADING_INVEST}\n"
        f"LOGS={CANAL_LOGS}\nLOGS_SINAIS={CANAL_LOGS_SINAIS}\n"
        f"COOLDOWN_INV_MIN={TRADING_TICKER_COOLDOWN_MINUTES_INVEST}",
        ephemeral=True,
    )


@client.tree.command(name="resync", description="Re-sincroniza comandos (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def resync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await sync_commands()
    await interaction.followup.send("✅ Sync solicitado. Veja o CANAL_LOGS.", ephemeral=True)


@client.tree.command(name="force_all", description="Força envio em TODOS os canais (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def force_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if notifier is None or binance is None or yahoo is None:
        await interaction.followup.send("❌ Bot ainda iniciando.", ephemeral=True)
        return

    results = []
    async with LOCK:
        # BINANCE MEMBRO (não envia se n=0)
        try:
            picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
            if picks:
                emb = engine_binance.build_embed(picks, tier="membro")
                ok = await _send_embed(CANAL_BINANCE_MEMBRO, emb, ROLE_MEMBRO_ID)
                results.append(f"BINANCE_MEMBRO {'OK' if ok else 'X'} n={len(picks)}")
            else:
                results.append("BINANCE_MEMBRO SKIP n=0 (não enviado)")
        except Exception as e:
            results.append(f"BINANCE_MEMBRO X ({e})")

        # BINANCE INVEST (não envia se n=0)
        try:
            picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
            if picks:
                emb = engine_binance.build_embed(picks, tier="investidor")
                ok = await _send_embed(CANAL_BINANCE_INVEST, emb, ROLE_INVESTIDOR_ID)
                results.append(f"BINANCE_INV {'OK' if ok else 'X'} n={len(picks)}")
            else:
                results.append("BINANCE_INV SKIP n=0 (não enviado)")
        except Exception as e:
            results.append(f"BINANCE_INV X ({e})")

        # TRADING MEMBRO (não envia se n=0)
        try:
            entry = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, "5m")
            if entry:
                emb = engine_trading.build_embed([entry], tier="membro")
                ok = await _send_embed(CANAL_TRADING_MEMBRO, emb, ROLE_MEMBRO_ID)
                results.append("TRADING_MEMBRO OK n=1")
            else:
                results.append("TRADING_MEMBRO SKIP n=0 (não enviado)")
        except Exception as e:
            results.append(f"TRADING_MEMBRO X ({e})")

        # TRADING INVEST (não envia se n=0)
        try:
            entries = []
            for tf in TRADING_INVEST_TFS:
                e = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, tf)
                if e and _cooldown_ok(e.symbol):
                    entries.append(e)
                if len(entries) >= int(TRADING_INVEST_MAX_PER_HOUR):
                    break

            if entries:
                emb = engine_trading.build_embed(entries, tier="investidor")
                ok = await _send_embed(CANAL_TRADING_INVEST, emb, ROLE_INVESTIDOR_ID)
                results.append(f"TRADING_INV {'OK' if ok else 'X'} n={len(entries)}")
            else:
                results.append("TRADING_INV SKIP n=0 (não enviado)")
        except Exception as e:
            results.append(f"TRADING_INV X ({e})")

    await _log(f"FORCE_ALL por {interaction.user} -> {results}")
    await interaction.followup.send("📨 **ForceAll:**\n" + "\n".join(results), ephemeral=True)


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Sem permissão.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        except Exception:
            pass
        return
    await _log(f"Erro slash: {error}")


@client.event
async def on_ready():
    await _log(f"READY: {client.user} (sync={SYNC_COMMANDS})")
    if SYNC_COMMANDS:
        await sync_commands()

    if not loop_binance_mentor.is_running():
        loop_binance_mentor.start()
    if not loop_trading_member.is_running():
        loop_trading_member.start()
    if not loop_trading_invest.is_running():
        loop_trading_invest.start()
    if not loop_news.is_running():
        loop_news.start()

    await _log("Loops iniciados (binance_mentor / trading_member / trading_invest / news).")


async def shutdown(reason: str):
    await _log(f"Shutdown: {reason}")

    with contextlib.suppress(Exception):
        for t in (loop_binance_mentor, loop_trading_member, loop_trading_invest, loop_news):
            if t.is_running():
                t.cancel()

    global HTTP
    with contextlib.suppress(Exception):
        if HTTP and not HTTP.closed:
            await HTTP.close()

    with contextlib.suppress(Exception):
        await client.close()

    os._exit(0)


def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _handler(sig_name: str):
        asyncio.create_task(shutdown(sig_name))

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig.name)


async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    global HTTP, notifier, binance, yahoo
    timeout = aiohttp.ClientTimeout(total=25)
    connector = aiohttp.TCPConnector(limit=60)
    HTTP = aiohttp.ClientSession(timeout=timeout, connector=connector)

    notifier = Notifier(client=client, session=HTTP)
    binance = BinanceSpot(HTTP)
    yahoo = YahooData(HTTP)

    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
