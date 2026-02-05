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
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "1").strip() == "1"

intents = discord.Intents.default()

HTTP: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
yahoo: YahooData | None = None

engine_binance = BinanceDipEngine()
engine_binomo = BinomoEngine()
engine_news = NewsEngine()

LOCK = asyncio.Lock()
ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)

_last_member_minute = None
_last_invest_minute = None
_last_news_minute = None


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


def _now_brt():
    return datetime.now(BR_TZ)

def _should_run_member(now: datetime) -> bool:
    hhmm = now.strftime("%H:%M")
    return hhmm in set(getattr(config, "MEMBRO_TIMES", []))

def _should_run_invest(now: datetime) -> bool:
    every = int(getattr(config, "INVESTIDOR_EVERY_MINUTES", 12))
    return (now.minute % every) == 0

def _should_run_news(now: datetime) -> bool:
    every = int(getattr(config, "NEWS_EVERY_MINUTES", 30))
    return (now.minute % every) == 0


async def sync_commands():
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            client.tree.copy_global_to(guild=guild)
            synced = await client.tree.sync(guild=guild)
            await log(f"SYNC GUILD {GUILD_ID}: {len(synced)} cmds -> {[c.name for c in synced]}")
        else:
            synced = await client.tree.sync()
            await log(f"SYNC GLOBAL: {len(synced)} cmds -> {[c.name for c in synced]}")
    except Exception as e:
        await log(f"Falha SYNC: {e}")


@tasks.loop(minutes=1)
async def loop_member():
    global _last_member_minute
    if notifier is None or binance is None or yahoo is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_member_minute == minute_key:
        return

    if not _should_run_member(now):
        await log(f"MEMBRO SKIP {minute_key} (fora da grade)")
        _last_member_minute = minute_key
        return

    _last_member_minute = minute_key

    async with LOCK:
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="membro")
        await notifier.send_discord(int(config.CANAL_BINANCE_MEMBRO), emb, role_ping_id=int(config.ROLE_MEMBRO_ID or 0))

        # Binomo membro: se não tiver entrada, não manda (reduz spam)
        entries = []
        e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
        if e15:
            entries.append(e15)
            emb2 = engine_binomo.build_embed(entries, tier="membro")
            await notifier.send_discord(int(config.CANAL_BINOMO_MEMBRO), emb2, role_ping_id=int(config.ROLE_MEMBRO_ID or 0))
        else:
            await log("MEMBRO BINOMO: sem entrada (ou mercado fechado).")

        await log(f"MEMBRO OK {minute_key}")


@loop_member.error
async def loop_member_error(err: Exception):
    await log(f"ERRO loop_member: {err}")


@tasks.loop(minutes=1)
async def loop_investidor():
    global _last_invest_minute
    if notifier is None or binance is None or yahoo is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_invest_minute == minute_key:
        return

    if not _should_run_invest(now):
        await log(f"INV SKIP {minute_key} (minuto não bate)")
        _last_invest_minute = minute_key
        return

    _last_invest_minute = minute_key

    async with LOCK:
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="investidor")
        await notifier.send_discord(int(config.CANAL_BINANCE_INVESTIDOR), emb, role_ping_id=int(config.ROLE_INVESTIDOR_ID or 0))

        # Binomo investidor: tenta 1m/5m/15m — se não achar, loga e segue.
        entries = []
        for tf in ("1m", "5m", "15m"):
            e = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), tf)
            if e:
                entries.append(e)

        if entries:
            emb2 = engine_binomo.build_embed(entries, tier="investidor")
            await notifier.send_discord(int(config.CANAL_BINOMO_INVESTIDOR), emb2, role_ping_id=int(config.ROLE_INVESTIDOR_ID or 0))
        else:
            await log("INV BINOMO: sem entradas válidas (ou mercado fechado).")

        await log(f"INV OK {minute_key}")


@loop_investidor.error
async def loop_investidor_error(err: Exception):
    await log(f"ERRO loop_investidor: {err}")


@tasks.loop(minutes=1)
async def loop_news():
    global _last_news_minute
    if notifier is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_news_minute == minute_key:
        return

    if not _should_run_news(now):
        _last_news_minute = minute_key
        return

    _last_news_minute = minute_key

    pt, en = engine_news.fetch()
    engine_news.mark_seen(pt + en)

    emb = engine_news.build_embed(pt, en)
    await notifier.send_discord(int(config.CANAL_NEWS_CRIPTO), emb)
    await log(f"NEWS OK {minute_key} pt={len(pt)} en={len(en)}")


@loop_news.error
async def loop_news_error(err: Exception):
    await log(f"ERRO loop_news: {err}")


# ── COMANDOS
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"✅ Online\nGUILD_ID={GUILD_ID or 'GLOBAL'}\n"
        f"BINANCE_INV={config.CANAL_BINANCE_INVESTIDOR}\nBINOMO_INV={config.CANAL_BINOMO_INVESTIDOR}\nNEWS={config.CANAL_NEWS_CRIPTO}\nLOGS={config.CANAL_LOGS}",
        ephemeral=True,
    )

@client.tree.command(name="resync", description="Re-sincroniza comandos (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def resync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await sync_commands()
    await interaction.followup.send("✅ Sync solicitado. Veja o CANAL_LOGS.", ephemeral=True)

@client.tree.command(name="force_investidor", description="Força ciclo investidor agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def force_investidor(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    now = _now_brt().strftime("%Y-%m-%d %H:%M")
    await log(f"FORCE_INV {now} por {interaction.user}")
    # executa uma vez
    async with LOCK:
        dips = await engine_binance.scan(binance, list(config.BINANCE_SYMBOLS))
        emb = engine_binance.build_embed(dips, tier="investidor")
        await notifier.send_discord(int(config.CANAL_BINANCE_INVESTIDOR), emb, role_ping_id=int(config.ROLE_INVESTIDOR_ID or 0))
    await interaction.followup.send("✅ Enviado Binance Investidor.", ephemeral=True)

@client.event
async def on_ready():
    await log(f"READY: {client.user} (sync={SYNC_COMMANDS})")

    if SYNC_COMMANDS:
        await sync_commands()

    if not loop_member.is_running():
        loop_member.start()
    if not loop_investidor.is_running():
        loop_investidor.start()
    if not loop_news.is_running():
        loop_news.start()

    await log("Loops iniciados (member/invest/news).")


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
