from __future__ import annotations

import os
import asyncio
import contextlib
import signal as os_signal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import tasks
from discord import app_commands
import feedparser
import pytz

import config
from atlas.engines_binance_mentor import BinanceMentorEngine
from atlas.engines_binomo_trading import BinomoTradingEngine, TradeEntry


BR_TZ = pytz.timezone("America/Sao_Paulo")

DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "1").strip() == "1"

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)
LOG_CHANNEL_ID = int(getattr(config, "CANAL_LOGS", 0) or 0)

# canais (membro vs investidor)
CH_NEWS_MEMBRO = int(getattr(config, "CANAL_NEWS_MEMBRO", 0) or 0)
CH_NEWS_INVEST = int(getattr(config, "CANAL_NEWS_INVESTIDOR", 0) or 0)

CH_BINANCE_MEMBRO = int(getattr(config, "CANAL_BINANCE_MEMBRO", 0) or 0)
CH_BINANCE_INVEST = int(getattr(config, "CANAL_BINANCE_INVESTIDOR", 0) or 0)

CH_TRADING_MEMBRO = int(getattr(config, "CANAL_BINOMO_MEMBRO", 0) or 0)
CH_TRADING_INVEST = int(getattr(config, "CANAL_BINOMO_INVESTIDOR", 0) or 0)

ROLE_MEMBRO_ID = int(getattr(config, "ROLE_MEMBRO_ID", 0) or 0)
ROLE_INVEST_ID = int(getattr(config, "ROLE_INVESTIDOR_ID", 0) or 0)

DISCORD_INVITE_LINK = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
BINANCE_REF_LINK = (getattr(config, "BINANCE_REF_LINK", "") or "").strip()
BINOMO_REF_LINK = (getattr(config, "BINOMO_REF_LINK", "") or "").strip()

NEWS_RSS_FEEDS_EN = list(getattr(config, "NEWS_RSS_FEEDS_EN", []) or [])

BINANCE_SYMBOLS = list(getattr(config, "BINANCE_SYMBOLS", []) or [])
BINOMO_TICKERS = list(getattr(config, "BINOMO_TICKERS", []) or [])

BINANCE_MEMBER_TIMES = list(getattr(config, "BINANCE_MEMBER_TIMES", ["09:00"]) or ["09:00"])
BINANCE_MEMBER_EVERY_DAYS = int(getattr(config, "BINANCE_MEMBER_EVERY_DAYS", 2) or 2)
BINANCE_INVEST_TIMES = list(getattr(config, "BINANCE_INVEST_TIMES", ["09:00", "18:00"]) or ["09:00", "18:00"])

TRADING_MEMBER_TIMES = list(getattr(config, "TRADING_MEMBER_TIMES", ["12:00"]) or ["12:00"])
TRADING_INVEST_ON_MINUTE = int(getattr(config, "TRADING_INVEST_ON_MINUTE", 0) or 0)
TRADING_INVEST_MAX_PER_HOUR = int(getattr(config, "TRADING_INVEST_MAX_PER_HOUR", 3) or 3)
TRADING_INVEST_TFS = list(getattr(config, "TRADING_INVEST_TFS", ["5m", "15m"]) or ["5m", "15m"])

TRADING_TICKER_COOLDOWN_MINUTES_INVEST = int(getattr(config, "TRADING_TICKER_COOLDOWN_MINUTES_INVEST", 180) or 180)

NEWS_EVERY_MINUTES = int(getattr(config, "NEWS_EVERY_MINUTES", 30) or 30)

intents = discord.Intents.default()
HTTP: aiohttp.ClientSession | None = None

# Engines
mentor = BinanceMentorEngine()
trading = BinomoTradingEngine()

LOCK = asyncio.Lock()

# Estado em memória (cooldown + dedupe news)
last_binance_member_day_key: Optional[str] = None
last_binance_member_sent_date: Optional[str] = None
last_binance_invest_day_key: Optional[str] = None

last_member_trading_day_key: Optional[str] = None
last_invest_trading_hour_key: Optional[str] = None

last_news_minute_key: Optional[str] = None
seen_news_en: set[str] = set()

# cooldown por ticker (premium)
last_trade_sent_ts: Dict[str, float] = {}


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


def _masked(label: str, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return f"[{label}]({url})"


async def _tg_send_html(text_html: str) -> Tuple[bool, str]:
    """
    Telegram sem depender de outros arquivos:
    - envia HTML (links mascarados)
    - quebra em blocos se ficar grande
    """
    if HTTP is None:
        return False, "HTTP session não iniciada"
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "TELEGRAM token/chat_id vazio"

    def _split(txt: str, limit: int = 3500) -> List[str]:
        txt = (txt or "").strip()
        if len(txt) <= limit:
            return [txt]
        out, cur = [], []
        size = 0
        for ln in txt.splitlines():
            ln2 = ln + "\n"
            if size + len(ln2) > limit and cur:
                out.append("".join(cur).strip())
                cur = [ln2]
                size = len(ln2)
            else:
                cur.append(ln2)
                size += len(ln2)
        if cur:
            out.append("".join(cur).strip())
        return [x for x in out if x]

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    ok_all = True
    last_err = ""

    for chunk in _split(text_html):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with HTTP.post(url, json=payload, timeout=20) as r:
                if r.status != 200:
                    ok_all = False
                    try:
                        last_err = (await r.text())[:200]
                    except Exception:
                        last_err = f"HTTP {r.status}"
        except Exception as e:
            ok_all = False
            last_err = str(e)

    return ok_all, last_err or ""


async def _log(msg: str):
    if not LOG_CHANNEL_ID:
        return
    ch = client.get_channel(LOG_CHANNEL_ID)
    if ch is None:
        try:
            ch = await client.fetch_channel(LOG_CHANNEL_ID)
        except Exception:
            return
    with contextlib.suppress(Exception):
        await ch.send(f"📡 {msg}")


async def _send_embed(channel_id: int, embed: discord.Embed, role_ping_id: int = 0) -> Tuple[bool, str]:
    if not channel_id:
        return False, "channel_id=0"
    ch = client.get_channel(channel_id)
    if ch is None:
        try:
            ch = await client.fetch_channel(channel_id)
        except Exception as e:
            return False, f"fetch_channel: {e}"

    content = ""
    if role_ping_id:
        content = f"<@&{role_ping_id}>"

    try:
        await ch.send(content=content, embed=embed)
        return True, ""
    except Exception as e:
        return False, str(e)


def _market_closed() -> bool:
    # Forex/Índices no Yahoo normalmente fecham no fim de semana.
    return datetime.utcnow().weekday() >= 5


# ─────────────────────────────
# Restrição: comandos só no canal admin
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
        with contextlib.suppress(Exception):
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)


client = AtlasClient()


async def _sync_commands():
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
# NEWS PT/EN (sem link, fontes no final) + Telegram (modo membro)
# ─────────────────────────────
def _clean(s: str) -> str:
    return (s or "").strip().replace("\n", " ").replace("  ", " ")


def _pt_headline(en: str) -> str:
    # tradução offline focada em títulos
    t = _clean(en)
    low = t.lower()

    # padrões rápidos
    rep = [
        ("shares jump", "ações sobem"),
        ("jumps", "sobe"),
        ("jump", "sobe"),
        ("rockets", "dispara"),
        ("surges", "dispara"),
        ("tumbles", "cai forte"),
        ("falls", "cai"),
        ("drops", "cai"),
        ("plunges", "despenca"),
        ("under fire", "sob pressão"),
        ("lawsuit", "processo"),
        ("regulation", "regulação"),
        ("market", "mercado"),
        ("crypto", "cripto"),
        ("exchange", "exchange"),
        ("stablecoin", "stablecoin"),
        ("u.s.", "EUA"),
        ("eu", "União Europeia"),
        ("u.k.", "Reino Unido"),
    ]

    out = t
    for a, b in rep:
        if a in low:
            out = out.replace(a, b).replace(a.title(), b)

    # capitaliza
    return out[:1].upper() + out[1:] if out else t


async def _fetch_news_lines(max_items: int = 12) -> Tuple[List[Tuple[str, str]], List[str]]:
    """
    Retorna: [ (pt, en), ... ], sources[]
    Aceita NEWS_RSS_FEEDS_EN como:
      - ["url", "url2"...]
      - [("CoinDesk","url"), ...]
    """
    items: List[Tuple[str, str]] = []
    sources: List[str] = []

    for it in NEWS_RSS_FEEDS_EN:
        if isinstance(it, (tuple, list)) and len(it) == 2:
            src, url = str(it[0]), str(it[1])
        else:
            src, url = "RSS", str(it)

        try:
            feed = feedparser.parse(url)
            if getattr(feed, "bozo", False):
                continue
            sources.append(src)
            for entry in (feed.entries or [])[:10]:
                en = _clean(getattr(entry, "title", ""))
                if not en:
                    continue
                pt = _pt_headline(en)
                items.append((pt, en))
        except Exception:
            continue

    # dedupe + “visto”
    out: List[Tuple[str, str]] = []
    for pt, en in items:
        key = en.lower()
        if key in seen_news_en:
            continue
        seen_news_en.add(key)
        out.append((pt, en))
        if len(out) >= max_items:
            break

    return out, sorted(set(sources))


def _build_news_embed(pairs: List[Tuple[str, str]], sources: List[str], tier: str) -> discord.Embed:
    e = discord.Embed(
        title=f"📰 Atlas Newsletter — Cripto (PT/EN) • {tier}",
        description="Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.",
        color=0x3498DB,
    )

    if not pairs:
        e.add_field(name="📌 Sem notícias novas", value="Nada novo neste ciclo.", inline=False)
    else:
        blocks = []
        for i, (pt, en) in enumerate(pairs, 1):
            blocks.append(f"**{i}) 🇧🇷** {pt}\n**{i}) 🇺🇸** {en}")
        e.add_field(name="🗞️ Notícias", value="\n\n".join(blocks)[:1024], inline=False)

    if sources:
        e.add_field(name="📎 Fontes (referência)", value=", ".join(sources)[:1024], inline=False)

    ctas = []
    if DISCORD_INVITE_LINK:
        ctas.append(f"🚀 {_masked('Entre no Discord e acompanhe ao vivo', DISCORD_INVITE_LINK)}")
    if BINANCE_REF_LINK:
        ctas.append(f"💠 {_masked('Acesse aqui e comece a investir', BINANCE_REF_LINK)}")
    if BINOMO_REF_LINK:
        ctas.append(f"🎯 {_masked('Acesse aqui e liberar acesso', BINOMO_REF_LINK)}")
    if ctas:
        e.add_field(name="✨ Acesso rápido", value="\n".join(ctas)[:1024], inline=False)

    e.set_footer(text=f"Atlas v6 • {_now_brt().strftime('%d/%m/%Y %H:%M')} BRT")
    return e


def _build_news_telegram_html(pairs: List[Tuple[str, str]], sources: List[str]) -> str:
    def esc(x: str) -> str:
        return (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = []
    parts.append("📰 <b>Atlas Newsletter — Cripto (PT/EN)</b>")
    parts.append("Texto direto (sem link). Fontes no final apenas para referência.")
    parts.append("🧠 Educacional — não é recomendação financeira.\n")

    for i, (pt, en) in enumerate(pairs, 1):
        parts.append(f"<b>{i}) 🇧🇷</b> {esc(pt)}")
        parts.append(f"<b>{i}) 🇺🇸</b> {esc(en)}")
        parts.append("")

    if sources:
        parts.append("📎 <b>Fontes (referência)</b>")
        parts.append(esc(", ".join(sources)))

    parts.append("")
    if DISCORD_INVITE_LINK:
        parts.append("🚀 <b>Tempo real no Discord</b>")
        parts.append(f'Entre na Atlas Community: <a href="{esc(DISCORD_INVITE_LINK)}">Clique para entrar</a>')
        parts.append("Conteúdo educacional para ajudar você a decidir melhor o que fazer com seu dinheiro.")
    if BINANCE_REF_LINK:
        parts.append(f'💠 Binance: <a href="{esc(BINANCE_REF_LINK)}">Acesse aqui</a>')
    if BINOMO_REF_LINK:
        parts.append(f'🎯 Binomo: <a href="{esc(BINOMO_REF_LINK)}">Acesse aqui</a>')

    return "\n".join(parts)


@tasks.loop(minutes=1)
async def loop_news():
    global last_news_minute_key
    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if last_news_minute_key == minute_key:
        return

    if (now.minute % NEWS_EVERY_MINUTES) != 0:
        last_news_minute_key = minute_key
        return

    last_news_minute_key = minute_key

    pairs, sources = await _fetch_news_lines(max_items=12)
    if not pairs:
        await _log("NEWS: sem itens novos.")
        return

    # Discord
    emb_m = _build_news_embed(pairs[:4], sources, "MEMBRO")
    emb_i = _build_news_embed(pairs[:7], sources, "INVESTIDOR")

    if CH_NEWS_MEMBRO:
        ok, err = await _send_embed(CH_NEWS_MEMBRO, emb_m, 0)
        if not ok:
            await _log(f"NEWS MEMBRO falhou: {err}")

    if CH_NEWS_INVEST:
        ok, err = await _send_embed(CH_NEWS_INVEST, emb_i, 0)
        if not ok:
            await _log(f"NEWS INVEST falhou: {err}")

    # Telegram (sempre modo membro)
    html_txt = _build_news_telegram_html(pairs[:4], sources)
    ok_tg, err_tg = await _tg_send_html(html_txt)
    if not ok_tg:
        await _log(f"NEWS Telegram falhou: {err_tg}")
    else:
        await _log("NEWS: Discord + Telegram OK")


# ─────────────────────────────
# Binance Mentor (Investimento)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_binance_mentor():
    global last_binance_member_day_key, last_binance_member_sent_date, last_binance_invest_day_key

    if HTTP is None:
        return

    # BinanceSpot compat: vamos importar de forma tardia (pra não quebrar se não existir)
    try:
        from binance_spot import BinanceSpot
    except Exception:
        return

    binance = BinanceSpot(HTTP)

    now = _now_brt()
    day_key = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")

    # MEMBRO: 1 recomendação a cada 2 dias (no horário fixo)
    if hhmm in set(BINANCE_MEMBER_TIMES):
        # checa a cada 2 dias
        if last_binance_member_sent_date is None:
            last_binance_member_sent_date = day_key  # trava hoje (primeira vez)
        else:
            try:
                last_dt = datetime.strptime(last_binance_member_sent_date, "%Y-%m-%d")
                if (now.replace(tzinfo=None) - last_dt).days < BINANCE_MEMBER_EVERY_DAYS:
                    return
            except Exception:
                pass

        if last_binance_member_day_key != day_key:
            picks = await mentor.scan_1h(binance, BINANCE_SYMBOLS, top_n=2)
            emb = mentor.build_embed(picks, tier="membro")
            ok, err = await _send_embed(CH_BINANCE_MEMBRO, emb, ROLE_MEMBRO_ID)
            if ok:
                last_binance_member_day_key = day_key
                last_binance_member_sent_date = day_key
                await _log(f"BINANCE MEMBRO OK {day_key} {hhmm}")
            else:
                await _log(f"BINANCE MEMBRO falhou: {err}")

    # INVESTIDOR: 2 por dia (09:00 e 18:00)
    if hhmm in set(BINANCE_INVEST_TIMES) and last_binance_invest_day_key != (day_key + hhmm):
        picks = await mentor.scan_1h(binance, BINANCE_SYMBOLS, top_n=3)
        emb = mentor.build_embed(picks, tier="investidor")
        ok, err = await _send_embed(CH_BINANCE_INVEST, emb, ROLE_INVEST_ID)
        if ok:
            last_binance_invest_day_key = (day_key + hhmm)
            await _log(f"BINANCE INVEST OK {day_key} {hhmm}")
        else:
            await _log(f"BINANCE INVEST falhou: {err}")


# ─────────────────────────────
# Binomo Trading (qualidade)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_trading():
    global last_member_trading_day_key, last_invest_trading_hour_key

    if HTTP is None:
        return

    try:
        from yahoo_data import YahooData
    except Exception:
        return

    yahoo = YahooData(HTTP)

    now = _now_brt()
    day_key = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")
    hour_key = now.strftime("%Y-%m-%d %H")

    # se mercado fechado (fim de semana), não envia nada (só log)
    if _market_closed():
        return

    # MEMBRO: 1/dia em horários definidos (M5)
    if hhmm in set(TRADING_MEMBER_TIMES) and last_member_trading_day_key != (day_key + hhmm):
        best = await trading.scan_best(yahoo, BINOMO_TICKERS, "5m")
        if best:
            emb = trading.build_embed([best], tier="membro")
            ok, err = await _send_embed(CH_TRADING_MEMBRO, emb, ROLE_MEMBRO_ID)
            if ok:
                last_member_trading_day_key = (day_key + hhmm)
                await _log(f"TRADING MEMBRO OK {day_key} {hhmm}")
            else:
                await _log(f"TRADING MEMBRO falhou: {err}")
        else:
            await _log(f"TRADING MEMBRO: sem entrada válida ({day_key} {hhmm})")

    # INVESTIDOR: 1/h no minuto X, até 3 entradas (M5/M15)
    if now.minute == TRADING_INVEST_ON_MINUTE and last_invest_trading_hour_key != hour_key:
        entries: List[TradeEntry] = []
        for tf in TRADING_INVEST_TFS:
            best = await trading.scan_best(yahoo, BINOMO_TICKERS, tf)
            if best:
                entries.append(best)

        # aplica cooldown por ticker (premium)
        filtered: List[TradeEntry] = []
        now_ts = now.timestamp()
        cd_sec = TRADING_TICKER_COOLDOWN_MINUTES_INVEST * 60
        for e in sorted(entries, key=lambda x: x.score, reverse=True):
            last = last_trade_sent_ts.get(e.ticker, 0.0)
            if (now_ts - last) < cd_sec:
                continue
            filtered.append(e)
            last_trade_sent_ts[e.ticker] = now_ts
            if len(filtered) >= TRADING_INVEST_MAX_PER_HOUR:
                break

        if filtered:
            emb = trading.build_embed(filtered, tier="investidor")
            ok, err = await _send_embed(CH_TRADING_INVEST, emb, ROLE_INVEST_ID)
            if ok:
                last_invest_trading_hour_key = hour_key
                await _log(f"TRADING INVEST OK {hour_key} n={len(filtered)}")
            else:
                await _log(f"TRADING INVEST falhou: {err}")
        else:
            # qualidade: sem setup => sem spam no canal (só log)
            last_invest_trading_hour_key = hour_key
            await _log(f"TRADING INVEST: sem entradas válidas {hour_key}")


# ─────────────────────────────
# Comandos
# ─────────────────────────────
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"✅ Online\n"
        f"GUILD={GUILD_ID or 'GLOBAL'}\n"
        f"NEWS_MEMBRO={CH_NEWS_MEMBRO}\nNEWS_INVEST={CH_NEWS_INVEST}\n"
        f"BINANCE_MEMBRO={CH_BINANCE_MEMBRO}\nBINANCE_INVEST={CH_BINANCE_INVEST}\n"
        f"TRADING_MEMBRO={CH_TRADING_MEMBRO}\nTRADING_INVEST={CH_TRADING_INVEST}\n"
        f"Telegram={'ON' if (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) else 'OFF'}\n",
        ephemeral=True,
    )


@client.tree.command(name="resync", description="Re-sincroniza comandos (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def resync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await _sync_commands()
    await interaction.followup.send("✅ Sync solicitado. Veja o CANAL_LOGS.", ephemeral=True)


@client.tree.command(name="force_all", description="Força envio em TODOS os canais (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def force_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if HTTP is None:
        await interaction.followup.send("❌ HTTP não iniciou.", ephemeral=True)
        return

    report = []

    async with LOCK:
        # NEWS (força)
        pairs, sources = await _fetch_news_lines(max_items=12)
        emb_m = _build_news_embed(pairs[:4], sources, "MEMBRO")
        emb_i = _build_news_embed(pairs[:7], sources, "INVESTIDOR")

        ok1, err1 = await _send_embed(CH_NEWS_MEMBRO, emb_m, 0)
        ok2, err2 = await _send_embed(CH_NEWS_INVEST, emb_i, 0)
        ok_tg, err_tg = await _tg_send_html(_build_news_telegram_html(pairs[:4], sources))

        report.append(f"NEWS_MEMBRO {'✅' if ok1 else '❌'}")
        report.append(f"NEWS_INVEST {'✅' if ok2 else '❌'}")
        report.append(f"NEWS_TG {'✅' if ok_tg else '❌'} {err_tg[:60]}")

        # Binance mentor
        try:
            from binance_spot import BinanceSpot
            binance = BinanceSpot(HTTP)
            picks = await mentor.scan_1h(binance, BINANCE_SYMBOLS, top_n=3)
            emb_bm = mentor.build_embed(picks, tier="membro")
            emb_bi = mentor.build_embed(picks, tier="investidor")

            ok, err = await _send_embed(CH_BINANCE_MEMBRO, emb_bm, ROLE_MEMBRO_ID)
            report.append(f"BINANCE_MEMBRO {'✅' if ok else '❌'} {err[:40]}")
            ok, err = await _send_embed(CH_BINANCE_INVEST, emb_bi, ROLE_INVEST_ID)
            report.append(f"BINANCE_INVEST {'✅' if ok else '❌'} {err[:40]}")
        except Exception as e:
            report.append(f"BINANCE ❌ {str(e)[:60]}")

        # Trading (força, pode dar sem entradas)
        try:
            from yahoo_data import YahooData
            yahoo = YahooData(HTTP)

            best5 = await trading.scan_best(yahoo, BINOMO_TICKERS, "5m")
            best15 = await trading.scan_best(yahoo, BINOMO_TICKERS, "15m")

            emb_tm = trading.build_embed([best5] if best5 else [], tier="membro")
            ok, err = await _send_embed(CH_TRADING_MEMBRO, emb_tm, ROLE_MEMBRO_ID)
            report.append(f"TRADING_MEMBRO {'✅' if ok else '❌'} {err[:40]}")

            entries = [x for x in [best5, best15] if x]
            emb_ti = trading.build_embed(entries, tier="investidor")
            ok, err = await _send_embed(CH_TRADING_INVEST, emb_ti, ROLE_INVEST_ID)
            report.append(f"TRADING_INVEST {'✅' if ok else '❌'} {err[:40]} n={len(entries)}")
        except Exception as e:
            report.append(f"TRADING ❌ {str(e)[:60]}")

    await _log("FORCE_ALL: " + " | ".join(report))
    await interaction.followup.send("📨 ForceAll: " + " | ".join(report), ephemeral=True)


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


@client.event
async def on_ready():
    await _log(f"READY: {client.user} (sync={SYNC_COMMANDS})")
    if SYNC_COMMANDS:
        await _sync_commands()

    if not loop_news.is_running():
        loop_news.start()
    if not loop_binance_mentor.is_running():
        loop_binance_mentor.start()
    if not loop_trading.is_running():
        loop_trading.start()

    await _log("Loops iniciados: news + binance_mentor + trading")


async def _shutdown(reason: str):
    await _log(f"Shutdown: {reason}")

    with contextlib.suppress(Exception):
        for t in (loop_news, loop_binance_mentor, loop_trading):
            if t.is_running():
                t.cancel()

    global HTTP
    with contextlib.suppress(Exception):
        if HTTP and not HTTP.closed:
            await HTTP.close()

    with contextlib.suppress(Exception):
        await client.close()

    os._exit(0)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _handler(sig_name: str):
        asyncio.create_task(_shutdown(sig_name))

    for sig in (os_signal.SIGTERM, os_signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig.name)


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    global HTTP
    timeout = aiohttp.ClientTimeout(total=25)
    connector = aiohttp.TCPConnector(limit=60)
    HTTP = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async with client:
        await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
