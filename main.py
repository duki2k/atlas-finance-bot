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
from engines_binomo import BinomoEngine, is_market_open_for_non_crypto, is_crypto_ticker
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

def _should_run_member_now() -> bool:
    now = datetime.now(BR_TZ)
    hhmm = now.strftime("%H:%M")
    return hhmm in set(getattr(config, "MEMBRO_TIMES", []))

def _minutes_mod(n: int) -> bool:
    now = datetime.now(BR_TZ)
    return (now.minute % n) == 0

@tasks.loop(seconds=20)
async def loop_member():
    if notifier is None or binance is None or yahoo is None:
        return
    now = datetime.now(BR_TZ)
    if now.second > 10:
        return
    if not _should_run_member_now():
        return
    if LOCK.locked():
        return

    async with LOCK:
        # BINANCE MEMBRO
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="membro")
        await notifier.send_discord(int(config.CANAL_BINANCE_MEMBRO), emb, role_ping_id=int(config.ROLE_MEMBRO_ID or 0))
        await notifier.send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINANCE), engine_binance.build_telegram(dips, "membro"))

        # BINOMO MEMBRO (somente 15m pra ser “menos entradas” e mais qualidade)
        entries = []
        e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
        if e15:
            entries.append(e15)
        # se mercado fechado (não-cripto), não manda
        if not entries:
            await log("MEMBRO BINOMO: mercado fechado ou sem entrada (15m).")
        else:
            emb2 = engine_binomo.build_embed(entries, tier="membro")
            await notifier.send_discord(int(config.CANAL_BINOMO_MEMBRO), emb2, role_ping_id=int(config.ROLE_MEMBRO_ID or 0))
            await notifier.send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINOMO), engine_binomo.build_telegram(entries, "membro"))

        await log("MEMBRO: envios executados.")

@tasks.loop(seconds=20)
async def loop_investidor():
    if notifier is None or binance is None or yahoo is None:
        return
    now = datetime.now(BR_TZ)
    if now.second > 10:
        return

    every = int(getattr(config, "INVESTIDOR_EVERY_MINUTES", 12))
    if not _minutes_mod(every):
        return

    if LOCK.locked():
        return

    async with LOCK:
        # BINANCE INVESTIDOR: top dips (5/h garantido por agenda)
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="investidor")
        await notifier.send_discord(int(config.CANAL_BINANCE_INVESTIDOR), emb, role_ping_id=int(config.ROLE_INVESTIDOR_ID or 0))
        await notifier.send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINANCE), engine_binance.build_telegram(dips, "investidor"))

        # BINOMO INVESTIDOR: 1m/5m/15m (manda antes do slot)
        entries = []
        e1  = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "1m")
        e5  = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "5m")
        e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
        for x in (e1, e5, e15):
            if x:
                entries.append(x)

        if not entries:
            # se for fim de semana, avisa no log e não spamma canal
            wd = datetime.utcnow().weekday()
            if wd >= 5:
                await log("INV BINOMO: mercado fechado (fim de semana). Sem envio.")
            else:
                await log("INV BINOMO: sem entradas válidas agora.")
        else:
            emb2 = engine_binomo.build_embed(entries, tier="investidor")
            await notifier.send_discord(int(config.CANAL_BINOMO_INVESTIDOR), emb2, role_ping_id=int(config.ROLE_INVESTIDOR_ID or 0))
            await notifier.send_telegram(bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_BINOMO), engine_binomo.build_telegram(entries, "investidor"))

        await log("INVESTIDOR: envios executados.")

@tasks.loop(seconds=30)
async def loop_news():
    if notifier is None:
        return
    now = datetime.now(BR_TZ)
    if now.second > 10:
        return
    if not _minutes_mod(int(getattr(config, "NEWS_EVERY_MINUTES", 30))):
        return

    items = engine_news.fetch()
    if items:
        engine_news.mark_seen(items)

    emb = engine_news.build_embed(items)
    await notifier.send_discord(int(config.CANAL_NEWS_CRIPTO), emb, role_ping_id=0)

    if bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_NEWS):
        await notifier.send_telegram(True, engine_news.build_telegram(items))

    await log(f"NEWS: enviados {len(items)} itens.")

# ─────────────────────────────
# COMANDOS (novos, e só admin)
# ─────────────────────────────
@tree.command(name="status", description="Status do Atlas Radar v4 (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        "📡 **Atlas Radar v4**\n"
        f"Binance membro: `{config.CANAL_BINANCE_MEMBRO}` | investidor: `{config.CANAL_BINANCE_INVESTIDOR}`\n"
        f"Binomo  membro: `{config.CANAL_BINOMO_MEMBRO}`  | investidor: `{config.CANAL_BINOMO_INVESTIDOR}`\n"
        f"News channel: `{config.CANAL_NEWS_CRIPTO}` | Logs: `{config.CANAL_LOGS}`\n"
        f"Telegram: `{config.TELEGRAM_ENABLED}`\n",
        ephemeral=True
    )

@tree.command(name="force_binance", description="Força envio Binance (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(tier=[
    app_commands.Choice(name="membro", value="membro"),
    app_commands.Choice(name="investidor", value="investidor"),
])
async def force_binance(interaction: discord.Interaction, tier: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if notifier is None or binance is None:
        await interaction.followup.send("❌ Bot ainda iniciando.", ephemeral=True)
        return
    async with LOCK:
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier=tier.value)
        ch = int(config.CANAL_BINANCE_MEMBRO if tier.value == "membro" else config.CANAL_BINANCE_INVESTIDOR)
        ping = int(config.ROLE_MEMBRO_ID if tier.value == "membro" else config.ROLE_INVESTIDOR_ID or 0)
        await notifier.send_discord(ch, emb, role_ping_id=ping)
    await interaction.followup.send("✅ Enviado.", ephemeral=True)

@tree.command(name="force_binomo", description="Força envio Binomo (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(tier=[
    app_commands.Choice(name="membro", value="membro"),
    app_commands.Choice(name="investidor", value="investidor"),
])
async def force_binomo(interaction: discord.Interaction, tier: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if notifier is None or yahoo is None:
        await interaction.followup.send("❌ Bot ainda iniciando.", ephemeral=True)
        return
    async with LOCK:
        entries = []
        if tier.value == "membro":
            e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
            if e15: entries.append(e15)
            ch = int(config.CANAL_BINOMO_MEMBRO)
            ping = int(config.ROLE_MEMBRO_ID or 0)
        else:
            for tf in ("1m","5m","15m"):
                e = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), tf)
                if e: entries.append(e)
            ch = int(config.CANAL_BINOMO_INVESTIDOR)
            ping = int(config.ROLE_INVESTIDOR_ID or 0)

        if not entries:
            await interaction.followup.send("📭 Sem entradas (ou mercado fechado).", ephemeral=True)
            return

        emb = engine_binomo.build_embed(entries, tier=tier.value)
        await notifier.send_discord(ch, emb, role_ping_id=ping)
    await interaction.followup.send("✅ Enviado.", ephemeral=True)

@tree.command(name="news_now", description="Força newsletter agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def news_now(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    items = engine_news.fetch()
    if items:
        engine_news.mark_seen(items)
    emb = engine_news.build_embed(items)
    await notifier.send_discord(int(config.CANAL_NEWS_CRIPTO), emb, role_ping_id=0)
    if bool(config.TELEGRAM_ENABLED and config.TELEGRAM_SEND_NEWS):
        await notifier.send_telegram(True, engine_news.build_telegram(items))
    await interaction.followup.send(f"✅ News enviada ({len(items)} itens).", ephemeral=True)

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
