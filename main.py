import os
import asyncio
import contextlib
import signal
from datetime import datetime

import aiohttp
import discord
import pytz
from discord.ext import tasks
from discord import app_commands

import config
from binance_spot import BinanceSpot
from notifier import Notifier
from radar import RadarEngine, BR_TZ

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
            await _deny(interaction, "⛔ Comandos disponíveis apenas no servidor.")
            return False
        if interaction.channel_id != ADMIN_CHANNEL_ID:
            await _deny(interaction, f"⛔ Use os comandos apenas em <#{ADMIN_CHANNEL_ID}>.")
            return False
        return True

tree = AtlasTree(client)

HTTP_SESSION: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
engine = RadarEngine()

LOCK = asyncio.Lock()

# slots (evita duplicar)
_last_1m = None
_last_5m = None
_last_15m = None
_last_4h = None


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


async def _post_signals(tier: str, interval: str, force: bool):
    if notifier is None or binance is None:
        return 0, 0
    if not getattr(config, "RADAR_ENABLED", False):
        return 0, 0
    if engine.paused() and not force:
        return 0, 0

    if tier == "membro":
        symbols = list(getattr(config, "WATCHLIST_MEMBRO", []))
        channel_id = int(getattr(config, "CANAL_MEMBRO", 0) or 0)
        role_ping = int(getattr(config, "ROLE_MEMBRO_ID", 0) or 0)
    else:
        symbols = list(getattr(config, "WATCHLIST_INVESTIDOR", []))
        channel_id = int(getattr(config, "CANAL_INVESTIDOR", 0) or 0)
        role_ping = int(getattr(config, "ROLE_INVESTIDOR_ID", 0) or 0)

    if not symbols or not channel_id:
        return 0, 0

    sigs = await engine.scan(binance, tier=tier, interval=interval, symbols=symbols)

    sent = 0
    for s in sigs:
        if force or engine._can_send(s):
            emb = engine.build_embed(s)
            await notifier.send_discord(channel_id, emb, role_ping_id=role_ping)
            await notifier.send_telegram(bool(getattr(config, "TELEGRAM_ENABLED", True)), engine.build_telegram(s))
            sent += 1

    return sent, len(sigs)


@tasks.loop(seconds=10)
async def investidor_loop():
    global _last_1m, _last_5m, _last_15m

    if notifier is None or binance is None:
        return

    now = datetime.now(BR_TZ)
    if now.second > 10:
        return

    slot = now.strftime("%Y-%m-%d %H:%M")

    if LOCK.locked():
        return

    async with LOCK:
        # 1m
        if _last_1m != slot:
            sent, cand = await _post_signals("investidor", "1m", force=False)
            await log(f"INV 1m slot {slot}: candidatos={cand} enviados={sent}")
            _last_1m = slot

        # 5m
        if now.minute % 5 == 0 and _last_5m != slot:
            sent, cand = await _post_signals("investidor", "5m", force=False)
            await log(f"INV 5m slot {slot}: candidatos={cand} enviados={sent}")
            _last_5m = slot

        # 15m
        if now.minute % 15 == 0 and _last_15m != slot:
            sent, cand = await _post_signals("investidor", "15m", force=False)
            await log(f"INV 15m slot {slot}: candidatos={cand} enviados={sent}")
            _last_15m = slot


@tasks.loop(seconds=20)
async def membro_loop():
    global _last_4h

    if notifier is None or binance is None:
        return

    now = datetime.now(BR_TZ)
    if now.second > 10:
        return

    # 4h em horas múltiplas de 4, no minuto fixo
    if now.hour % 4 != 0:
        return
    if now.minute != int(getattr(config, "MEMBRO_MINUTE", 5)):
        return

    slot = now.strftime("%Y-%m-%d %H:%M")
    if _last_4h == slot:
        return

    if LOCK.locked():
        return

    async with LOCK:
        sent, cand = await _post_signals("membro", "4h", force=False)
        await log(f"MEMBRO 4h slot {slot}: candidatos={cand} enviados={sent}")
        _last_4h = slot


# ─────────────────────────────
# Commands (SÓ ESTES)
# ─────────────────────────────
@tree.command(name="status", description="Status geral do Radar Pro (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"📡 **Atlas Radar Pro (SPOT-only)**\n"
        f"RADAR_ENABLED: `{getattr(config, 'RADAR_ENABLED', False)}`\n"
        f"Paused: `{engine.paused()}`\n"
        f"CANAL_MEMBRO: `{getattr(config, 'CANAL_MEMBRO', 0)}` | watchlist={len(getattr(config,'WATCHLIST_MEMBRO',[]))}\n"
        f"CANAL_INVESTIDOR: `{getattr(config, 'CANAL_INVESTIDOR', 0)}` | watchlist={len(getattr(config,'WATCHLIST_INVESTIDOR',[]))}\n"
        f"Telegram: `{getattr(config, 'TELEGRAM_ENABLED', False)}`\n",
        ephemeral=True
    )

@tree.command(name="scan_membro", description="Força envio MEMBRO (4h) agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def scan_membro(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if LOCK.locked():
        await interaction.followup.send("⏳ Já tem execução em andamento.", ephemeral=True)
        return
    async with LOCK:
        sent, cand = await _post_signals("membro", "4h", force=True)
    await interaction.followup.send(f"✅ MEMBRO 4h: candidatos={cand} enviados={sent}", ephemeral=True)

@tree.command(name="scan_investidor", description="Força envio INVESTIDOR (1m/5m/15m) (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(timeframe=[
    app_commands.Choice(name="1m", value="1m"),
    app_commands.Choice(name="5m", value="5m"),
    app_commands.Choice(name="15m", value="15m"),
    app_commands.Choice(name="all", value="all"),
])
async def scan_investidor(interaction: discord.Interaction, timeframe: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if LOCK.locked():
        await interaction.followup.send("⏳ Já tem execução em andamento.", ephemeral=True)
        return

    sent_total = 0
    cand_total = 0

    async with LOCK:
        if timeframe.value in ("1m", "all"):
            s, c = await _post_signals("investidor", "1m", force=True)
            sent_total += s; cand_total += c
        if timeframe.value in ("5m", "all"):
            s, c = await _post_signals("investidor", "5m", force=True)
            sent_total += s; cand_total += c
        if timeframe.value in ("15m", "all"):
            s, c = await _post_signals("investidor", "15m", force=True)
            sent_total += s; cand_total += c

    await interaction.followup.send(f"✅ INVESTIDOR {timeframe.value}: candidatos={cand_total} enviados={sent_total}", ephemeral=True)

@tree.command(name="pause", description="Pausa alertas por X minutos (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def pause(interaction: discord.Interaction, minutos: int):
    minutes = max(1, min(1440, int(minutos)))
    engine.pause_minutes(minutes)
    await interaction.response.send_message(f"⏸️ Alertas pausados por {minutes} minutos.", ephemeral=True)

@tree.command(name="resume", description="Retoma alertas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def resume(interaction: discord.Interaction):
    engine.resume()
    await interaction.response.send_message("▶️ Alertas retomados.", ephemeral=True)

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

    if not investidor_loop.is_running():
        investidor_loop.start()
    if not membro_loop.is_running():
        membro_loop.start()


async def shutdown(reason: str):
    await log(f"Shutdown: {reason}")
    with contextlib.suppress(Exception):
        if investidor_loop.is_running():
            investidor_loop.cancel()
    with contextlib.suppress(Exception):
        if membro_loop.is_running():
            membro_loop.cancel()

    global HTTP_SESSION
    with contextlib.suppress(Exception):
        if HTTP_SESSION and not HTTP_SESSION.closed:
            await HTTP_SESSION.close()

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

    global HTTP_SESSION, notifier, binance
    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(limit=50)
    HTTP_SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector)

    notifier = Notifier(client=client, session=HTTP_SESSION)
    binance = BinanceSpot(HTTP_SESSION)

    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
