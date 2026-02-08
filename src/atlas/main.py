import os
import asyncio
import contextlib
import signal
from datetime import datetime, timedelta
from typing import List, Optional

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

# compat: alguns configs antigos usam CANAL_TRADING_*, outros CANAL_BINOMO_*
CANAL_TRADING_MEMBRO = int(getattr(config, "CANAL_BINOMO_MEMBRO", getattr(config, "CANAL_TRADING_MEMBRO", 0)) or 0)
CANAL_TRADING_INVEST = int(getattr(config, "CANAL_BINOMO_INVESTIDOR", getattr(config, "CANAL_TRADING_INVESTIDOR", 0)) or 0)

ROLE_MEMBRO_ID = int(getattr(config, "ROLE_MEMBRO_ID", 0) or 0)
ROLE_INVESTIDOR_ID = int(getattr(config, "ROLE_INVESTIDOR_ID", 0) or 0)

# ─────────────────────────────
# Schedules (mentor / trading / news)
# ─────────────────────────────
BINANCE_SYMBOLS: List[str] = list(getattr(config, "BINANCE_SYMBOLS", []))

BINANCE_MEMBER_TIMES: List[str] = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]))
BINANCE_MEMBER_EVERY_DAYS: int = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2))
BINANCE_INVEST_TIMES: List[str] = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]))

TRADING_TICKERS: List[str] = list(getattr(config, "BINOMO_TICKERS", []))
TRADING_MEMBER_TIMES: List[str] = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]))
TRADING_INVEST_ON_MINUTE: int = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0))
TRADING_INVEST_MAX_PER_HOUR: int = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3))
TRADING_INVEST_TFS: List[str] = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]))

TRADING_TICKER_COOLDOWN_MINUTES_INVEST: int = int(getattr(config, "TRADING_TICKER_COOLDOWN_MINUTES_INVEST", 180))

NEWS_EVERY_MINUTES: int = int(getattr(config, "NEWS_EVERY_MINUTES", 180))
NEWS_TIMES: List[str] = list(getattr(config, "NEWS_TIMES", []))  # opcional: lista HH:MM
# compat: NEWS_MEMBER_MAX/NEWS_INVEST_MAX (antigo) OU NEWS_MAX_ITEMS_MEMBER/NEWS_MAX_ITEMS_INVEST (novo)
NEWS_MEMBER_MAX: int = int(getattr(config, "NEWS_MEMBER_MAX", getattr(config, "NEWS_MAX_ITEMS_MEMBER", 4)))
NEWS_INVEST_MAX: int = int(getattr(config, "NEWS_INVEST_MAX", getattr(config, "NEWS_MAX_ITEMS_INVEST", 6)))


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _minute_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


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


def _day_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _day_ok_every_days(dt: datetime, every_days: int) -> bool:
    # usa "dias desde epoch" pra ficar determinístico
    epoch = datetime(1970, 1, 1, tzinfo=dt.tzinfo)
    days = (dt.date() - epoch.date()).days
    every = max(1, int(every_days))
    return (days % every) == 0


def _should_run_by_times(now: datetime, times: List[str]) -> bool:
    return _hhmm(now) in set(times or [])


def _should_run_trading_invest(now: datetime) -> bool:
    return now.minute == int(TRADING_INVEST_ON_MINUTE)


def _masked(label: str, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    # Discord: link "encurtado" (texto clicável)
    return f"[{label}]({url})"


# ─────────────────────────────────────────────────────────────
# NEWS
# ─────────────────────────────────────────────────────────────
def _build_news_embed(lines, tier: str, max_items: int) -> discord.Embed:
    title = f"📰 Atlas Newsletter — Cripto (PT/EN) • {tier.upper()}"
    desc = "Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira."
    e = discord.Embed(title=title, description=desc, color=0x3498DB)

    # notícias (mesma notícia em PT/EN)
    blocks = []
    sources = []
    for i, it in enumerate(lines[:max_items], start=1):
        en = (getattr(it, "en", "") or "").strip()
        pt = (getattr(it, "pt", "") or "").strip()
        src = (getattr(it, "source", "") or "").strip()

        if src and src not in sources:
            sources.append(src)

        # PT primeiro (pedido)
        blocks.append(
            f"**{i})** 🇧🇷 {pt}\n"
            f"🇺🇸 {en}"
        )

    e.add_field(name="🗞️ Notícias", value="\n\n".join(blocks)[:1024] if blocks else "Sem itens agora.", inline=False)

    if sources:
        e.add_field(name="📎 Fontes (referência)", value=", ".join(sources)[:1024], inline=False)

    # CTA (sem “indicação” + links "encurtados" no Discord)
    discord_invite = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
    binance_ref = (getattr(config, "BINANCE_REF_LINK", "") or "").strip()
    binomo_ref = (getattr(config, "BINOMO_REF_LINK", "") or "").strip()

    ctas = []
    if discord_invite:
        ctas.append(f"🚀 {_masked('Entre no Discord para alertas ao vivo', discord_invite)}")
    if binance_ref:
        ctas.append(f"💎 {_masked('Abra sua conta Binance e receba benefícios', binance_ref)}")
    if binomo_ref:
        ctas.append(f"🎯 {_masked('Acesse a Binomo e desbloqueie benefícios', binomo_ref)}")

    if ctas:
        e.add_field(name="✨ Acesso rápido", value="\\n".join(ctas)[:1024], inline=False)

    e.set_footer(text=f"Atlas v6 • {_now_brt().strftime('%d/%m/%Y %H:%M')} BRT")
    return e


def _build_news_telegram(lines, max_items: int) -> str:
    head = "📰 Atlas Newsletter — Cripto (PT/EN)\nTexto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.\n"
    parts = []
    sources = []

    for i, it in enumerate(lines[:max_items], start=1):
        en = (getattr(it, "en", "") or "").strip()
        pt = (getattr(it, "pt", "") or "").strip()
        src = (getattr(it, "source", "") or "").strip()

        if src and src not in sources:
            sources.append(src)

        parts.append(
            f"{i}) 🇧🇷 {pt}\n"
            f"   🇺🇸 {en}"
        )

    tail = ""
    if sources:
        tail += "\n\n📎 Fontes (referência): " + "; ".join(sources)

    discord_invite = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
    if discord_invite:
        tail += "\n\n🚀 Entre no Discord (tempo real): " + discord_invite
        tail += "\n(mais rápido, mais claro, e com entradas + mentor)"

    # CTAs extras (texto curto)
    binance_ref = (getattr(config, "BINANCE_REF_LINK", "") or "").strip()
    if binance_ref:
        tail += "\n\n💎 Binance: abra sua conta e receba benefícios: " + binance_ref

    binomo_ref = (getattr(config, "BINOMO_REF_LINK", "") or "").strip()
    if binomo_ref:
        tail += "\n🎯 Binomo: desbloqueie benefícios na plataforma: " + binomo_ref

    body = "\n\n".join(parts) if parts else "Sem itens agora."
    return head + "\n\n" + body + tail


# ─────────────────────────────
# Discord client + Tree (bloqueio no admin channel)
# ─────────────────────────────
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

# dedupe/slots
_slot_binance_member: set[str] = set()
_slot_binance_invest: set[str] = set()
_slot_trading_member: set[str] = set()
_slot_trading_invest: set[str] = set()
_slot_news: set[str] = set()

# dedupe de notícias por headline (EN)
_seen_news_en: set[str] = set()

# cooldown por ticker (premium trading)
_last_trade_ts_by_ticker: dict[str, float] = {}


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


# ─────────────────────────────
# BINANCE MENTOR (INVESTIMENTO)
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
        # MEMBRO: 1 recomendação a cada X dias (horário fixo)
        if hhmm in set(BINANCE_MEMBER_TIMES) and _day_ok_every_days(now, BINANCE_MEMBER_EVERY_DAYS):
            slot = f"BINANCE_MEM:{day}:{hhmm}"
            if slot not in _slot_binance_member:
                _slot_binance_member.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                emb = engine_binance.build_embed(picks, tier="membro")
                ok = await _send_embed(CANAL_BINANCE_MEMBRO, emb, ROLE_MEMBRO_ID)
                await _log(f"BINANCE_MEMBRO {'OK' if ok else 'X'} {slot}")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_MEMBRO skip {minute}")

        # INVESTIDOR: horários do dia (2/dia)
        if hhmm in set(BINANCE_INVEST_TIMES):
            slot = f"BINANCE_INV:{day}:{hhmm}"
            if slot not in _slot_binance_invest:
                _slot_binance_invest.add(slot)
                picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
                emb = engine_binance.build_embed(picks, tier="investidor")
                ok = await _send_embed(CANAL_BINANCE_INVEST, emb, ROLE_INVESTIDOR_ID)
                await _log(f"BINANCE_INV {'OK' if ok else 'X'} {slot}")
        else:
            if LOG_SKIPS:
                await _log(f"BINANCE_INV skip {minute}")


@loop_binance_mentor.error
async def loop_binance_mentor_error(err: Exception):
    await _log(f"ERRO loop_binance_mentor: {err}")


# ─────────────────────────────
# BINOMO TRADING
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_trading_member():
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    hhmm = _hhmm(now)
    minute = _minute_key(now)

    should_run = hhmm in set(TRADING_MEMBER_TIMES)
    if not should_run:
        if LOG_SKIPS:
            await _log(f"TRADING_MEMBRO skip {minute}")
        return

    slot = f"TRADING_MEM:{_day_key(now)}:{hhmm}"
    if slot in _slot_trading_member:
        return
    _slot_trading_member.add(slot)

    async with LOCK:
        entry = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, "5m")
        emb = engine_trading.build_embed([entry] if entry else [], tier="membro")
        ok = await _send_embed(CANAL_TRADING_MEMBRO, emb, ROLE_MEMBRO_ID)
        await _log_sinais(f"TRADING_MEMBRO {'OK' if ok else 'X'} {slot} n={1 if entry else 0}")


@loop_trading_member.error
async def loop_trading_member_error(err: Exception):
    await _log(f"ERRO loop_trading_member: {err}")


@tasks.loop(minutes=1)
async def loop_trading_invest():
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    minute = _minute_key(now)

    should_run = _should_run_trading_invest(now)
    if not should_run:
        if LOG_SKIPS:
            await _log(f"TRADING_INV skip {minute}")
        return

    slot = f"TRADING_INV:{_day_key(now)}:{now.strftime('%H')}"
    if slot in _slot_trading_invest:
        return
    _slot_trading_invest.add(slot)

    async with LOCK:
        # fim de semana = mercado fechado (Yahoo FX/índices costuma parar)
        if datetime.utcnow().weekday() >= 5:
            await _log_sinais(f"TRADING_INV SKIP {minute} (mercado fechado)")
            return

        entries = []
        for tf in TRADING_INVEST_TFS:
            e = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, tf)
            if e and _cooldown_ok(e.symbol):
                entries.append(e)
            if len(entries) >= int(TRADING_INVEST_MAX_PER_HOUR):
                break

        emb = engine_trading.build_embed(entries, tier="investidor")
        ok = await _send_embed(CANAL_TRADING_INVEST, emb, ROLE_INVESTIDOR_ID)
        await _log_sinais(f"TRADING_INV {'OK' if ok else 'X'} {slot} n={len(entries)}")


@loop_trading_invest.error
async def loop_trading_invest_error(err: Exception):
    await _log(f"ERRO loop_trading_invest: {err}")


# ─────────────────────────────
# NEWS LOOP  ✅ (arrumado: await + tuple + dedupe + Telegram)
# ─────────────────────────────
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
        lines, _sources = await engine_news.fetch_lines(limit=max(NEWS_INVEST_MAX, NEWS_MEMBER_MAX, 6))
        if not lines:
            if LOG_SKIPS:
                await _log(f"NEWS sem itens {slot}")
            return

        # dedupe por headline EN (não repetir notícia no próximo ciclo)
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

        lines = fresh

        # 1) Discord MEMBRO
        if CANAL_NEWS_MEMBRO:
            emb_m = _build_news_embed(lines, tier="membro", max_items=NEWS_MEMBER_MAX)
            okm = await _send_embed(CANAL_NEWS_MEMBRO, emb_m, ROLE_MEMBRO_ID)
        else:
            okm = False

        # 2) Discord INVESTIDOR
        if CANAL_NEWS_INVEST:
            emb_i = _build_news_embed(lines, tier="investidor", max_items=NEWS_INVEST_MAX)
            oki = await _send_embed(CANAL_NEWS_INVEST, emb_i, ROLE_INVESTIDOR_ID)
        else:
            oki = False

        # 3) Telegram (formato membro)
        if (getattr(notifier, "tg_token", "") or "").strip() and (getattr(notifier, "tg_chat_id", "") or "").strip():
            try:
                text = _build_news_telegram(lines, max_items=NEWS_MEMBER_MAX)
                await notifier.send_telegram_text(text, disable_preview=True)
            except Exception as e:
                await _log(f"Falha Telegram NEWS {slot}: {e}")

        await _log(f"NEWS OK {slot} n={len(lines)} disc_m={okm} disc_i={oki}")


@loop_news.error
async def loop_news_error(err: Exception):
    await _log(f"ERRO loop_news: {err}")


# ─────────────────────────────
# COMANDOS (ADMIN)
# ─────────────────────────────
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        "✅ Online\n"
        f"GUILD={GUILD_ID or 'GLOBAL'}\n"
        f"ADMIN={ADMIN_CHANNEL_ID}\n"
        f"NEWS_MEMBRO={CANAL_NEWS_MEMBRO}\nNEWS_INVEST={CANAL_NEWS_INVEST}\n"
        f"BINANCE_MEMBRO={CANAL_BINANCE_MEMBRO}\nBINANCE_INV={CANAL_BINANCE_INVEST}\n"
        f"TRADING_MEMBRO={CANAL_TRADING_MEMBRO}\nTRADING_INV={CANAL_TRADING_INVEST}\n"
        f"LOGS={CANAL_LOGS}\nLOGS_SINAIS={CANAL_LOGS_SINAIS}\n"
        f"NEWS_EVERY_MINUTES={NEWS_EVERY_MINUTES}\nNEWS_TIMES={NEWS_TIMES}\n"
        f"BINANCE_MEMBER_TIMES={BINANCE_MEMBER_TIMES} every_days={BINANCE_MEMBER_EVERY_DAYS}\n"
        f"BINANCE_INVEST_TIMES={BINANCE_INVEST_TIMES}\n"
        f"TRADING_MEMBER_TIMES={TRADING_MEMBER_TIMES}\n"
        f"TRADING_INVEST_ON_MINUTE={TRADING_INVEST_ON_MINUTE} tfs={TRADING_INVEST_TFS} max/h={TRADING_INVEST_MAX_PER_HOUR}\n"
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
        # NEWS
        try:
            lines, _sources = await engine_news.fetch_lines(limit=max(NEWS_INVEST_MAX, NEWS_MEMBER_MAX, 6))
            emb_m = _build_news_embed(lines, tier="membro", max_items=NEWS_MEMBER_MAX)
            emb_i = _build_news_embed(lines, tier="investidor", max_items=NEWS_INVEST_MAX)
            ok_m = await _send_embed(CANAL_NEWS_MEMBRO, emb_m, ROLE_MEMBRO_ID) if CANAL_NEWS_MEMBRO else False
            ok_i = await _send_embed(CANAL_NEWS_INVEST, emb_i, ROLE_INVESTIDOR_ID) if CANAL_NEWS_INVEST else False

            # Telegram também no force
            tg_ok = False
            if (getattr(notifier, "tg_token", "") or "").strip() and (getattr(notifier, "tg_chat_id", "") or "").strip():
                text = _build_news_telegram(lines, max_items=NEWS_MEMBER_MAX)
                await notifier.send_telegram_text(text, disable_preview=True)
                tg_ok = True

            results.append(f"NEWS {'OK' if (ok_m or ok_i) else 'X'} (disc_m={ok_m} disc_i={ok_i} tg={tg_ok})")
        except Exception as e:
            results.append(f"NEWS X ({e})")

        # BINANCE MEMBRO
        try:
            picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
            emb = engine_binance.build_embed(picks, tier="membro")
            ok = await _send_embed(CANAL_BINANCE_MEMBRO, emb, ROLE_MEMBRO_ID)
            results.append(f"BINANCE_MEMBRO {'OK' if ok else 'X'} -> {CANAL_BINANCE_MEMBRO}")
        except Exception as e:
            results.append(f"BINANCE_MEMBRO X ({e})")

        # BINANCE INVEST
        try:
            picks = await engine_binance.scan_1h(binance, BINANCE_SYMBOLS)
            emb = engine_binance.build_embed(picks, tier="investidor")
            ok = await _send_embed(CANAL_BINANCE_INVEST, emb, ROLE_INVESTIDOR_ID)
            results.append(f"BINANCE_INV {'OK' if ok else 'X'} -> {CANAL_BINANCE_INVEST}")
        except Exception as e:
            results.append(f"BINANCE_INV X ({e})")

        # TRADING MEMBRO
        try:
            entry = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, "5m")
            emb = engine_trading.build_embed([entry] if entry else [], tier="membro")
            ok = await _send_embed(CANAL_TRADING_MEMBRO, emb, ROLE_MEMBRO_ID)
            results.append(f"TRADING_MEMBRO {'OK' if ok else 'X'} -> {CANAL_TRADING_MEMBRO}")
        except Exception as e:
            results.append(f"TRADING_MEMBRO X ({e})")

        # TRADING INVEST
        try:
            entries = []
            for tf in TRADING_INVEST_TFS:
                e = await engine_trading.scan_timeframe(yahoo, TRADING_TICKERS, tf)
                if e and _cooldown_ok(e.symbol):
                    entries.append(e)
                if len(entries) >= int(TRADING_INVEST_MAX_PER_HOUR):
                    break
            emb = engine_trading.build_embed(entries, tier="investidor")
            ok = await _send_embed(CANAL_TRADING_INVEST, emb, ROLE_INVESTIDOR_ID)
            results.append(f"TRADING_INV {'OK' if ok else 'X'} -> {CANAL_TRADING_INVEST} n={len(entries)}")
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

    # valida config (evita deploy quebrado por nomes/ids errados)
    try:
        validate = getattr(config, "validate_config", None)
        if callable(validate):
            problems = validate()
            if problems:
                await _log("CONFIG: problemas encontrados:\n- " + "\n- ".join(problems))
    except Exception as e:
        await _log(f"CONFIG: erro ao validar: {e}")

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
