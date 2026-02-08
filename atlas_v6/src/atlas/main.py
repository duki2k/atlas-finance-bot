from __future__ import annotations

import os
import asyncio
import contextlib
import signal
from datetime import datetime
from typing import List, Optional, Tuple

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
from .engines_binomo_trading import BinomoTradingEngine, TradeEntry
from .engines_newsroom import NewsroomEngine


BR_TZ = pytz.timezone("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "1").strip() == "1"
LOG_SKIPS = (os.getenv("LOG_SKIPS") or "0").strip() == "1"  # por padrão: não spammar log


# ─────────────────────────────────────────────────────────────
# CONFIG (IDs)
# ─────────────────────────────────────────────────────────────
ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)
CANAL_LOGS = int(getattr(config, "CANAL_LOGS", 0) or 0)
CANAL_LOGS_SINAIS = int(getattr(config, "CANAL_LOGS_SINAIS", 0) or 0)

CANAL_NEWS_MEMBRO = int(getattr(config, "CANAL_NEWS_MEMBRO", 0) or 0)
CANAL_NEWS_INVEST = int(getattr(config, "CANAL_NEWS_INVESTIDOR", 0) or 0)

CANAL_BINANCE_MEMBRO = int(getattr(config, "CANAL_BINANCE_MEMBRO", 0) or 0)
CANAL_BINANCE_INVEST = int(getattr(config, "CANAL_BINANCE_INVESTIDOR", 0) or 0)

CANAL_TRADING_MEMBRO = int(getattr(config, "CANAL_BINOMO_MEMBRO", 0) or 0)
CANAL_TRADING_INVEST = int(getattr(config, "CANAL_BINOMO_INVESTIDOR", 0) or 0)

ROLE_MEMBRO_ID = int(getattr(config, "ROLE_MEMBRO_ID", 0) or 0)
ROLE_INVESTIDOR_ID = int(getattr(config, "ROLE_INVESTIDOR_ID", 0) or 0)


# ─────────────────────────────────────────────────────────────
# Schedules
# ─────────────────────────────────────────────────────────────
BINANCE_SYMBOLS: List[str] = list(getattr(config, "BINANCE_SYMBOLS", []))
BINOMO_TICKERS: List[str] = list(getattr(config, "BINOMO_TICKERS", []))

BINANCE_MEMBER_TIMES: List[str] = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]))
BINANCE_MEMBER_EVERY_DAYS: int = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2))
BINANCE_INVEST_TIMES: List[str] = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]))

TRADING_MEMBER_TIMES: List[str] = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]))
TRADING_INVEST_ON_MINUTE: int = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0))
TRADING_INVEST_MAX_PER_HOUR: int = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3))
TRADING_INVEST_TFS: List[str] = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]))
TRADING_TICKER_COOLDOWN_MINUTES_INVEST: int = int(getattr(config, "TRADING_TICKER_COOLDOWN_MINUTES_INVEST", 180))

NEWS_EVERY_MINUTES: int = int(getattr(config, "NEWS_EVERY_MINUTES", 180))
NEWS_TIMES: List[str] = list(getattr(config, "NEWS_TIMES", []))  # opcional: lista HH:MM
NEWS_MEMBER_MAX: int = int(getattr(config, "NEWS_MEMBER_MAX", 4))
NEWS_INVEST_MAX: int = int(getattr(config, "NEWS_INVEST_MAX", 6))


# ─────────────────────────────────────────────────────────────
# Discord client
# ─────────────────────────────────────────────────────────────
intents = discord.Intents.default()


class AtlasClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = AtlasTree(self)


class AtlasTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # trava todos os comandos no canal admin (se configurado)
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


# ─────────────────────────────────────────────────────────────
# Globals
# ─────────────────────────────────────────────────────────────
HTTP: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
yahoo: YahooData | None = None

engine_binance = BinanceMentorEngine()
engine_trading = BinomoTradingEngine()
engine_news = NewsroomEngine()

LOCK = asyncio.Lock()

# dedupe/slots
_slot_binance_member: set[str] = set()
_slot_binance_invest: set[str] = set()
_slot_trading_member: set[str] = set()
_slot_trading_invest: set[str] = set()
_slot_news: set[str] = set()

# cooldown por ticker (premium trading)
_last_trade_ts_by_ticker: dict[str, float] = {}


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _hhmm(now: datetime) -> str:
    return now.strftime("%H:%M")


def _date_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _hour_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H")


def _minute_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _day_ok_every_days(now: datetime, every_days: int) -> bool:
    if every_days <= 1:
        return True
    return (now.date().toordinal() % every_days) == 0


async def _log(msg: str, *, channel_id: int = 0):
    cid = int(channel_id or CANAL_LOGS or 0)
    if cid <= 0:
        return
    ch = client.get_channel(cid)
    if ch is None:
        with contextlib.suppress(Exception):
            ch = await client.fetch_channel(cid)
    if ch is None:
        return
    with contextlib.suppress(Exception):
        await ch.send(f"📡 {msg}")


async def _log_signal(msg: str):
    if CANAL_LOGS_SINAIS > 0:
        await _log(msg, channel_id=CANAL_LOGS_SINAIS)
    else:
        await _log(msg)


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


async def _send_or_fail(channel_id: int, embed: discord.Embed, *, role_ping: int = 0) -> Tuple[bool, str]:
    if notifier is None:
        return False, "notifier=None"
    if int(channel_id or 0) <= 0:
        return False, "canal_id=0"
    try:
        await notifier.send_discord(int(channel_id), embed, role_ping_id=int(role_ping or 0))
        return True, ""
    except Exception as e:
        return False, str(e)


def _cooldown_ok(ticker: str, now_ts: float, minutes: int) -> bool:
    last = _last_trade_ts_by_ticker.get(ticker, 0.0)
    if (now_ts - last) < (minutes * 60):
        return False
    _last_trade_ts_by_ticker[ticker] = now_ts
    return True


# ─────────────────────────────────────────────────────────────
# NEWS
# ─────────────────────────────────────────────────────────────
def _build_news_embed(lines, *, tier: str, max_items: int) -> discord.Embed:
    now = _now_brt().strftime("%d/%m/%Y %H:%M BRT")

    picked = list(lines)[: max(0, int(max_items))]
    title = f"📰 Atlas Newsletter — Cripto (PT/EN) • {tier.upper()}"
    e = discord.Embed(
        title=title,
        description=(
            "Texto direto (sem link). Fontes no final apenas para referência.\n"
            "🧠 Educacional — não é recomendação financeira."
        ),
        color=0x3498DB,
    )

    if not picked:
        e.add_field(name="📌 Sem notícias", value="Nada relevante no ciclo.", inline=False)
    else:
        blocks = []
        for i, it in enumerate(picked, 1):
            en = (getattr(it, "en", "") or "").strip()
            pt = (getattr(it, "pt", "") or "").strip()
            if not pt:
                pt = en
            blocks.append(
                f"**{i})** 🇺🇸 {en}\n"
                f"🇧🇷 {pt}"
            )
        e.add_field(name="🗞️ Notícias", value="\n\n".join(blocks)[:1024], inline=False)

    # fontes (somente referência)
    sources = []
    for it in picked:
        s = (getattr(it, "source", "") or "").strip()
        if s and s not in sources:
            sources.append(s)
    if sources:
        e.add_field(name="📎 Fontes (referência)", value=", ".join(sources)[:1024], inline=False)

    # CTA Discord
    discord_invite = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
    if discord_invite:
        e.add_field(
            name="🚀 Tempo real no Discord",
            value=f"Entre na Atlas Community para alertas ao vivo: {discord_invite}",
            inline=False,
        )

    e.set_footer(text=f"Atlas v6 • {now}")
    return e


def _build_news_telegram(lines, *, max_items: int) -> str:
    picked = list(lines)[: max(0, int(max_items))]
    head = (
        "📰 Atlas Newsletter — Cripto (PT/EN)\n"
        "Texto direto (sem link). Fontes no final apenas para referência.\n"
        "🧠 Educacional — não é recomendação financeira.\n"
    )
    if not picked:
        body = "\n📌 Sem notícias relevantes no ciclo."
    else:
        parts = []
        for i, it in enumerate(picked, 1):
            en = (getattr(it, "en", "") or "").strip()
            pt = (getattr(it, "pt", "") or "").strip() or en
            parts.append(
                f"{i}) EN: {en}\n"
                f"   PT: {pt}"
            )
        body = "\n\n" + "\n\n".join(parts)

    sources = []
    for it in picked:
        s = (getattr(it, "source", "") or "").strip()
        if s and s not in sources:
            sources.append(s)
    tail = ""
    if sources:
        tail += "\n\n📎 Fontes (referência): " + ", ".join(sources)

    discord_invite = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
    if discord_invite:
        tail += "\n\n🚀 Alertas em tempo real no Discord: " + discord_invite
        tail += "\n(mais rápido, mais claro, tudo em um lugar)"

    return head + body + tail


# ─────────────────────────────────────────────────────────────
# LOOPS
# ─────────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def loop_binance():
    if notifier is None or binance is None:
        return
    if not BINANCE_SYMBOLS:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    day = _date_key(now)

    async with LOCK:
        # MEMBRO: 1 recomendação a cada N dias, nos horários BINANCE_MEMBER_TIMES
        if hhmm in set(BINANCE_MEMBER_TIMES) and _day_ok_every_days(now, BINANCE_MEMBER_EVERY_DAYS):
            slot = f"BINANCE_MEMBRO:{day}:{hhmm}"
            if slot not in _slot_binance_member:
                _slot_binance_member.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                emb = engine_binance.build_embed(picks, tier="membro")
                ok, err = await _send_or_fail(CANAL_BINANCE_MEMBRO, emb, role_ping=ROLE_MEMBRO_ID)
                if ok:
                    await _log_signal(f"BINANCE_MEMBRO enviado {slot} picks={len(picks)}")
                else:
                    await _log(f"Falha BINANCE_MEMBRO {slot}: {err}")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_MEMBRO skip {day}:{hhmm}")

        # INVESTIDOR: 2/dia (horários BINANCE_INVEST_TIMES)
        if hhmm in set(BINANCE_INVEST_TIMES):
            slot = f"BINANCE_INV:{day}:{hhmm}"
            if slot not in _slot_binance_invest:
                _slot_binance_invest.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                emb = engine_binance.build_embed(picks, tier="investidor")
                ok, err = await _send_or_fail(CANAL_BINANCE_INVEST, emb, role_ping=ROLE_INVESTIDOR_ID)
                if ok:
                    await _log_signal(f"BINANCE_INV enviado {slot} picks={len(picks)}")
                else:
                    await _log(f"Falha BINANCE_INV {slot}: {err}")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_INV skip {day}:{hhmm}")


@loop_binance.error
async def loop_binance_error(err: Exception):
    await _log(f"ERRO loop_binance: {err}")


@tasks.loop(minutes=1)
async def loop_trading():
    if notifier is None or yahoo is None:
        return
    if not BINOMO_TICKERS:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    day = _date_key(now)
    hour = _hour_key(now)
    now_ts = now.timestamp()

    async with LOCK:
        # MEMBRO: 1 entrada/dia (M5) nos horários TRADING_MEMBER_TIMES
        if hhmm in set(TRADING_MEMBER_TIMES):
            slot = f"TRADING_MEMBRO:{day}:{hhmm}"
            if slot not in _slot_trading_member:
                _slot_trading_member.add(slot)
                cand = await engine_trading.scan_candidates(yahoo, BINOMO_TICKERS, "5m", limit=10)
                if cand:
                    emb = engine_trading.build_embed([cand[0]], tier="membro")
                    ok, err = await _send_or_fail(CANAL_TRADING_MEMBRO, emb, role_ping=ROLE_MEMBRO_ID)
                    if ok:
                        await _log_signal(f"TRADING_MEMBRO enviado {slot} ticker={cand[0].ticker}")
                    else:
                        await _log(f"Falha TRADING_MEMBRO {slot}: {err}")
                else:
                    # sem spam no canal — só log
                    await _log_signal(f"TRADING_MEMBRO sem entrada {slot}")
        else:
            if LOG_SKIPS:
                await _log(f"TRADING_MEMBRO skip {day}:{hhmm}")

        # INVESTIDOR: 1/h (no minuto fixo), até N entradas combinando timeframes
        if int(now.minute) == int(TRADING_INVEST_ON_MINUTE):
            slot = f"TRADING_INV:{hour}"
            if slot not in _slot_trading_invest:
                _slot_trading_invest.add(slot)

                # candidatos por timeframe
                cands: List[TradeEntry] = []
                for tf in TRADING_INVEST_TFS:
                    cands.extend(await engine_trading.scan_candidates(yahoo, BINOMO_TICKERS, tf, limit=15))

                # rank global + unique + cooldown por ticker
                cands.sort(key=lambda x: x.score, reverse=True)
                picked: List[TradeEntry] = []
                used: set[str] = set()
                for c in cands:
                    if c.ticker in used:
                        continue
                    if not _cooldown_ok(c.ticker, now_ts, TRADING_TICKER_COOLDOWN_MINUTES_INVEST):
                        continue
                    used.add(c.ticker)
                    picked.append(c)
                    if len(picked) >= max(1, TRADING_INVEST_MAX_PER_HOUR):
                        break

                if picked:
                    emb = engine_trading.build_embed(picked, tier="investidor")
                    ok, err = await _send_or_fail(CANAL_TRADING_INVEST, emb, role_ping=ROLE_INVESTIDOR_ID)
                    if ok:
                        await _log_signal(f"TRADING_INV enviado {slot} n={len(picked)}")
                    else:
                        await _log(f"Falha TRADING_INV {slot}: {err}")
                else:
                    # mercado fechado? sem setups? só log
                    if now.weekday() >= 5:
                        await _log_signal(f"TRADING_INV mercado fechado (fim de semana) {slot}")
                    else:
                        await _log_signal(f"TRADING_INV sem entradas {slot}")
        else:
            if LOG_SKIPS:
                await _log(f"TRADING_INV skip {hour}:{now.minute:02d}")


@loop_trading.error
async def loop_trading_error(err: Exception):
    await _log(f"ERRO loop_trading: {err}")


@tasks.loop(minutes=1)
async def loop_news():
    if notifier is None:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    minute = _minute_key(now)

    should_run = False
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
        lines = engine_news.fetch_lines(limit=max(NEWS_INVEST_MAX, NEWS_MEMBER_MAX, 6))
        # 1) Discord MEMBRO
        if CANAL_NEWS_MEMBRO > 0:
            emb_m = _build_news_embed(lines, tier="membro", max_items=NEWS_MEMBER_MAX)
            ok, err = await _send_or_fail(CANAL_NEWS_MEMBRO, emb_m, role_ping=0)
            if not ok:
                await _log(f"Falha NEWS_MEMBRO {slot}: {err}")

        # 2) Discord INVESTIDOR
        if CANAL_NEWS_INVEST > 0:
            emb_i = _build_news_embed(lines, tier="investidor", max_items=NEWS_INVEST_MAX)
            ok, err = await _send_or_fail(CANAL_NEWS_INVEST, emb_i, role_ping=0)
            if not ok:
                await _log(f"Falha NEWS_INV {slot}: {err}")

        # 3) Telegram (formato membro)
        with contextlib.suppress(Exception):
            text = _build_news_telegram(lines, max_items=NEWS_MEMBER_MAX)
            await notifier.send_telegram_text(text, disable_preview=True)

        await _log_signal(f"NEWS enviado {slot} n={len(lines)}")


@loop_news.error
async def loop_news_error(err: Exception):
    await _log(f"ERRO loop_news: {err}")


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        (
            "✅ Online\n"
            f"GUILD={GUILD_ID or 'GLOBAL'}\n\n"
            f"Admin: <#{ADMIN_CHANNEL_ID}>\n"
            f"Logs: <#{CANAL_LOGS}>\n"
            f"News Membro: <#{CANAL_NEWS_MEMBRO}>\n"
            f"News Investidor: <#{CANAL_NEWS_INVEST}>\n"
            f"Binance Membro: <#{CANAL_BINANCE_MEMBRO}>\n"
            f"Binance Investidor: <#{CANAL_BINANCE_INVEST}>\n"
            f"Trading Membro: <#{CANAL_TRADING_MEMBRO}>\n"
            f"Trading Investidor: <#{CANAL_TRADING_INVEST}>\n\n"
            f"BINANCE_MEMBER_TIMES={BINANCE_MEMBER_TIMES} a cada {BINANCE_MEMBER_EVERY_DAYS}d\n"
            f"BINANCE_INVEST_TIMES={BINANCE_INVEST_TIMES}\n"
            f"TRADING_MEMBER_TIMES={TRADING_MEMBER_TIMES}\n"
            f"TRADING_INVEST: minuto={TRADING_INVEST_ON_MINUTE} max/h={TRADING_INVEST_MAX_PER_HOUR} tfs={TRADING_INVEST_TFS} cooldown={TRADING_TICKER_COOLDOWN_MINUTES_INVEST}m\n"
            f"NEWS: times={NEWS_TIMES or 'N/A'} every={NEWS_EVERY_MINUTES}m"
        ),
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

    results: List[str] = []

    async with LOCK:
        # NEWS
        try:
            lines = engine_news.fetch_lines(limit=max(NEWS_INVEST_MAX, NEWS_MEMBER_MAX, 6))
            emb_m = _build_news_embed(lines, tier="membro", max_items=NEWS_MEMBER_MAX)
            emb_i = _build_news_embed(lines, tier="investidor", max_items=NEWS_INVEST_MAX)
            okm, erm = await _send_or_fail(CANAL_NEWS_MEMBRO, emb_m)
            oki, eri = await _send_or_fail(CANAL_NEWS_INVEST, emb_i)
            try:
                text = _build_news_telegram(lines, max_items=NEWS_MEMBER_MAX)
                await notifier.send_telegram_text(text, disable_preview=True)
                tgr = "OK"
            except Exception as e:
                tgr = str(e)
            results.append(f"NEWS MEMBRO {'OK' if okm else 'X'} ({erm or 'ok'})")
            results.append(f"NEWS INVEST {'OK' if oki else 'X'} ({eri or 'ok'})")
            results.append(f"NEWS Telegram {'OK' if tgr=='OK' else 'X'} ({tgr if tgr!='OK' else 'ok'})")
        except Exception as e:
            results.append(f"NEWS X ({e})")

        # BINANCE
        try:
            picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
            embm = engine_binance.build_embed(picks, tier="membro")
            embi = engine_binance.build_embed(picks, tier="investidor")
            okm, erm = await _send_or_fail(CANAL_BINANCE_MEMBRO, embm, role_ping=ROLE_MEMBRO_ID)
            oki, eri = await _send_or_fail(CANAL_BINANCE_INVEST, embi, role_ping=ROLE_INVESTIDOR_ID)
            results.append(f"BINANCE_MEMBRO {'OK' if okm else 'X'} ({erm or 'ok'})")
            results.append(f"BINANCE_INV {'OK' if oki else 'X'} ({eri or 'ok'})")
        except Exception as e:
            results.append(f"BINANCE X ({e})")

        # TRADING
        try:
            cand_m = await engine_trading.scan_candidates(yahoo, BINOMO_TICKERS, "5m", limit=5)
            embm = engine_trading.build_embed([cand_m[0]] if cand_m else [], tier="membro")
            okm, erm = await _send_or_fail(CANAL_TRADING_MEMBRO, embm, role_ping=ROLE_MEMBRO_ID)
            results.append(f"TRADING_MEMBRO {'OK' if okm else 'X'} ({erm or 'ok'})")

            # invest: junta tfs e pega top N (sem aplicar cooldown no force)
            cands: List[TradeEntry] = []
            for tf in TRADING_INVEST_TFS:
                cands.extend(await engine_trading.scan_candidates(yahoo, BINOMO_TICKERS, tf, limit=10))
            cands.sort(key=lambda x: x.score, reverse=True)
            embi = engine_trading.build_embed(cands[: max(1, TRADING_INVEST_MAX_PER_HOUR)], tier="investidor")
            oki, eri = await _send_or_fail(CANAL_TRADING_INVEST, embi, role_ping=ROLE_INVESTIDOR_ID)
            results.append(f"TRADING_INV {'OK' if oki else 'X'} ({eri or 'ok'})")
        except Exception as e:
            results.append(f"TRADING X ({e})")

    await _log(f"FORCE_ALL por {interaction.user} -> {results}")
    await interaction.followup.send("📨 ForceAll: " + " | ".join(results), ephemeral=True)


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        with contextlib.suppress(Exception):
            if interaction.response.is_done():
                await interaction.followup.send("❌ Sem permissão.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return
    await _log(f"Erro slash: {error}")


# ─────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────
@client.event
async def on_ready():
    await _log(f"READY: {client.user} (sync={SYNC_COMMANDS})")

    if SYNC_COMMANDS:
        await sync_commands()

    for t in (loop_binance, loop_trading, loop_news):
        if not t.is_running():
            t.start()

    await _log("Loops iniciados (binance / trading / news).")


async def shutdown(reason: str):
    await _log(f"Shutdown: {reason}")

    with contextlib.suppress(Exception):
        for t in (loop_binance, loop_trading, loop_news):
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
