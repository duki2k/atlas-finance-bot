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
from notifier import Notifier
from binance_spot import BinanceSpot
from yahoo_data import YahooData
from engines_binance import BinanceDipEngine
from engines_binomo import BinomoEngine
from news_engine import NewsEngine

BR_TZ = pytz.timezone("America/Sao_Paulo")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "0").strip() == "1"

intents = discord.Intents.default()
client = discord.Client(intents=intents)

ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)

async def _deny(interaction: discord.Interaction, msg: str):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

class AtlasTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if ADMIN_CHANNEL_ID <= 0:
            return True
        if interaction.guild is None:
            await _deny(interaction, "⛔ Comandos apenas no servidor.")
            return False
        if interaction.channel_id != ADMIN_CHANNEL_ID:
            await _deny(interaction, f"⛔ Use comandos apenas em <#{ADMIN_CHANNEL_ID}>.")
            return False
        return True

tree = AtlasTree(client)

HTTP: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
yahoo: YahooData | None = None

engine_binance = BinanceDipEngine()
engine_binomo = BinomoEngine()
engine_news = NewsEngine()

LOCK = asyncio.Lock()

# “travas” por minuto para não spammar
_last_member_minute = ""
_last_invest_minute = ""
_last_news_minute = ""

async def log(msg: str):
    cid = int(getattr(config, "CANAL_LOGS", 0) or 0)
    if not cid:
        return
    ch = client.get_channel(cid)
    if ch is None:
        try:
            ch = await client.fetch_channel(cid)
        except Exception:
            return
    with contextlib.suppress(Exception):
        await ch.send(f"📡 {msg}")

def _minute_key() -> str:
    return datetime.now(BR_TZ).strftime("%Y-%m-%d %H:%M")

def _should_run_member_now(now: datetime) -> bool:
    hhmm = now.strftime("%H:%M")
    return hhmm in set(getattr(config, "MEMBRO_TIMES", []))

def _should_run_invest_now(now: datetime) -> bool:
    every = int(getattr(config, "INVESTIDOR_EVERY_MINUTES", 12))
    return (now.minute % every) == 0

def _should_run_news_now(now: datetime) -> bool:
    every = int(getattr(config, "NEWS_EVERY_MINUTES", 30))
    return (now.minute % every) == 0

async def _safe_send_discord(channel_id: int, embed: discord.Embed, ping: int = 0, tag: str = ""):
    try:
        await notifier.send_discord(channel_id, embed, role_ping_id=ping)
        return True
    except Exception as e:
        await log(f"Falha envio Discord {tag}: {e}")
        return False

async def _safe_send_telegram(enabled: bool, text: str, tag: str = ""):
    try:
        await notifier.send_telegram(enabled, text)
    except Exception as e:
        await log(f"Falha envio Telegram {tag}: {e}")

@tasks.loop(seconds=5)
async def loop_member():
    global _last_member_minute

    if notifier is None or binance is None or yahoo is None:
        return

    now = datetime.now(BR_TZ)
    mk = now.strftime("%Y-%m-%d %H:%M")
    if mk == _last_member_minute:
        return
    if not _should_run_member_now(now):
        return
    if LOCK.locked():
        return

    _last_member_minute = mk

    async with LOCK:
        # BINANCE MEMBRO
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="membro")
        ok = await _safe_send_discord(int(config.CANAL_BINANCE_MEMBRO), emb, ping=int(config.ROLE_MEMBRO_ID or 0), tag="BINANCE_MEMBRO")
        if ok:
            await _safe_send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINANCE), engine_binance.build_telegram(dips, "membro"), tag="BINANCE_MEMBRO")

        # BINOMO MEMBRO (somente 15m)
        entries = []
        e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
        if e15:
            entries.append(e15)

        if not entries:
            await log("MEMBRO BINOMO: sem entrada (ou mercado fechado).")
        else:
            emb2 = engine_binomo.build_embed(entries, tier="membro")
            ok2 = await _safe_send_discord(int(config.CANAL_BINOMO_MEMBRO), emb2, ping=int(config.ROLE_MEMBRO_ID or 0), tag="BINOMO_MEMBRO")
            if ok2:
                await _safe_send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINOMO), engine_binomo.build_telegram(entries, "membro"), tag="BINOMO_MEMBRO")

        await log(f"MEMBRO OK ({mk})")

@tasks.loop(seconds=5)
async def loop_investidor():
    global _last_invest_minute

    if notifier is None or binance is None or yahoo is None:
        return

    now = datetime.now(BR_TZ)
    mk = now.strftime("%Y-%m-%d %H:%M")
    if mk == _last_invest_minute:
        return
    if not _should_run_invest_now(now):
        return
    if LOCK.locked():
        return

    _last_invest_minute = mk

    async with LOCK:
        # BINANCE INVESTIDOR
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="investidor")
        ok = await _safe_send_discord(int(config.CANAL_BINANCE_INVESTIDOR), emb, ping=int(config.ROLE_INVESTIDOR_ID or 0), tag="BINANCE_INV")
        if ok:
            await _safe_send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINANCE), engine_binance.build_telegram(dips, "investidor"), tag="BINANCE_INV")

        # BINOMO INVESTIDOR: 1m/5m/15m
        entries = []
        for tf in ("1m", "5m", "15m"):
            e = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), tf)
            if e:
                entries.append(e)

        if not entries:
            # “bolsa fechada”: fim de semana => loga e não envia
            if datetime.utcnow().weekday() >= 5:
                await log("INV BINOMO: mercado fechado (fim de semana). Sem envio.")
            else:
                await log("INV BINOMO: sem entradas válidas.")
        else:
            emb2 = engine_binomo.build_embed(entries, tier="investidor")
            ok2 = await _safe_send_discord(int(config.CANAL_BINOMO_INVESTIDOR), emb2, ping=int(config.ROLE_INVESTIDOR_ID or 0), tag="BINOMO_INV")
            if ok2:
                await _safe_send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINOMO), engine_binomo.build_telegram(entries, "investidor"), tag="BINOMO_INV")

        await log(f"INVESTIDOR OK ({mk})")

@tasks.loop(seconds=10)
async def loop_news():
    global _last_news_minute

    if notifier is None:
        return

    now = datetime.now(BR_TZ)
    mk = now.strftime("%Y-%m-%d %H:%M")
    if mk == _last_news_minute:
        return
    if not _should_run_news_now(now):
        return

    _last_news_minute = mk

    items = engine_news.fetch()
    if items:
        engine_news.mark_seen(items)

    emb = engine_news.build_embed(items)
    await _safe_send_discord(int(config.CANAL_NEWS_CRIPTO), emb, ping=0, tag="NEWS")

    if bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_NEWS):
        await _safe_send_telegram(True, engine_news.build_telegram(items), tag="NEWS")

    await log(f"NEWS OK ({mk}) itens={len(items)}")

# ─────────────────────────────
# COMANDOS (admin)
# ─────────────────────────────
@tree.command(name="status", description="Status do Atlas Radar v4 (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        "📡 **Atlas Radar v4**\n"
        f"BINANCE membro: `{config.CANAL_BINANCE_MEMBRO}` | investidor: `{config.CANAL_BINANCE_INVESTIDOR}`\n"
        f"BINOMO  membro: `{config.CANAL_BINOMO_MEMBRO}` | investidor: `{config.CANAL_BINOMO_INVESTIDOR}`\n"
        f"NEWS: `{config.CANAL_NEWS_CRIPTO}` | LOGS: `{config.CANAL_LOGS}`\n"
        f"Telegram: `{config.TELEGRAM_ENABLED}`\n",
        ephemeral=True
    )

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await _deny(interaction, "❌ Sem permissão.")
        return
    await log(f"Erro slash: {error}")

@client.event
async def on_ready():
    await log(f"Conectado como {client.user}")

    if SYNC_COMMANDS:
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
                await log(f"Sync guild OK: {[c.name for c in synced]}")
            else:
                synced = await tree.sync()
                await log(f"Sync global OK: {[c.name for c in synced]}")
        except Exception as e:
            await log(f"Falha sync: {e}")

    if not loop_member.is_running():
        loop_member.start()
    if not loop_investidor.is_running():
        loop_investidor.start()
    if not loop_news.is_running():
        loop_news.start()

async def shutdown(reason: str):
    await log(f"Shutdown: {reason}")
    with contextlib.suppress(Exception):
        if loop_member.is_running(): loop_member.cancel()
        if loop_investidor.is_running(): loop_investidor.cancel()
        if loop_news.is_running(): loop_news.cancel()

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
