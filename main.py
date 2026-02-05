# main.py (Atlas Radar v3 - SPOT-only)
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

# ─────────────────────────────
# CommandTree com bloqueio de canal (discord.py compatível)
# ─────────────────────────────
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
radar_engine = RadarEngine()
binance: BinanceSpot | None = None
notifier: Notifier | None = None

RADAR_LOCK = asyncio.Lock()
last_slot = None


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


def _time_hhmm(now: datetime) -> str:
    return now.strftime("%H:%M")


@tasks.loop(seconds=10)
async def radar_loop():
    """
    Scaneia a cada minuto (sem drift) e dispara alertas relevantes.
    """
    global last_slot
    if notifier is None or binance is None:
        return
    if not getattr(config, "RADAR_ENABLED", False):
        return

    now = datetime.now(BR_TZ)

    # roda somente no segundo 0-9 e trava o slot por minuto
    if now.second > 9:
        return

    slot = now.strftime("%Y-%m-%d %H:%M")
    if last_slot == slot:
        return

    if RADAR_LOCK.locked():
        return

    async with RADAR_LOCK:
        sent, candidates = await radar_engine.run_cycle(binance, notifier, force=False)
        await log(f"Radar ciclo {slot}: candidatos={candidates} enviados={sent}")

    last_slot = slot


@tasks.loop(seconds=20)
async def pulse_loop():
    """
    “Pulso” profissional em horários fixos (BRT).
    """
    if notifier is None:
        return
    if not getattr(config, "PULSE_ENABLED", True):
        return

    now = datetime.now(BR_TZ)
    hhmm = _time_hhmm(now)
    times = set(getattr(config, "PULSE_TIMES_BRT", []))

    if hhmm not in times:
        return

    # evita duplicar no mesmo minuto
    key = now.strftime("%Y-%m-%d %H:%M")
    if getattr(pulse_loop, "_last", None) == key:
        return
    pulse_loop._last = key  # type: ignore

    emb = discord.Embed(
        title="🧠 Atlas Radar — Pulso do Mercado (SPOT)",
        description=(
            "📌 **Objetivo:** manter a galera antenada e disciplinada.\n\n"
            "✅ **O que fazer com o dinheiro (playbook):**\n"
            "• Se você investe: priorize **plano + DCA + diversificação**, evite FOMO.\n"
            "• Se você faz trades: opere só com **setup**, **stop** e risco pequeno.\n"
            "• Tenha caixa e regra: **não aumentar mão em emoção**.\n\n"
            "⚠️ Educacional — não é recomendação financeira."
        ),
        color=0x3498DB,
    )
    emb.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
    await notifier.send_discord_pulse(emb)
    await notifier.send_telegram(
        f"🧠 Atlas Radar — Pulso (SPOT)\n"
        f"Playbook:\n"
        f"- Investidor: DCA + diversificação, evite FOMO\n"
        f"- Trader: setup + stop + risco pequeno\n"
        f"- Disciplina > emoção\n\n"
        f"Educacional — não é recomendação financeira."
    )


# ─────────────────────────────
# Slash commands (admin)
# ─────────────────────────────
@tree.command(name="radar_status", description="Status do Atlas Radar (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def radar_status(interaction: discord.Interaction):
    paused = radar_engine.paused()
    await interaction.response.send_message(
        f"📡 **Atlas Radar v3**\n"
        f"RADAR_ENABLED: `{getattr(config, 'RADAR_ENABLED', False)}`\n"
        f"Paused: `{paused}`\n"
        f"Watchlist: `{len(getattr(config, 'WATCHLIST', []))}` ativos\n"
        f"Scan: `{getattr(config, 'SCAN_EVERY_SECONDS', 60)}s` (motor roda por minuto)\n",
        ephemeral=True,
    )

@tree.command(name="radar_agora", description="Força um ciclo de radar agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def radar_agora(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if notifier is None or binance is None:
        await interaction.followup.send("❌ Radar não inicializado.", ephemeral=True)
        return
    if RADAR_LOCK.locked():
        await interaction.followup.send("⏳ Já existe um ciclo em execução.", ephemeral=True)
        return
    async with RADAR_LOCK:
        sent, candidates = await radar_engine.run_cycle(binance, notifier, force=True)
    await interaction.followup.send(f"✅ Forçado: candidatos={candidates} enviados={sent}", ephemeral=True)

@tree.command(name="radar_pause", description="Pausa alertas por X minutos (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def radar_pause(interaction: discord.Interaction, minutos: int):
    radar_engine.pause_minutes(max(1, min(1440, int(minutos))))
    await interaction.response.send_message(f"⏸️ Alertas pausados por {minutos} minutos.", ephemeral=True)

@tree.command(name="radar_resume", description="Retoma alertas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def radar_resume(interaction: discord.Interaction):
    radar_engine.resume()
    await interaction.response.send_message("▶️ Alertas retomados.", ephemeral=True)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await _deny(interaction, "❌ Você não tem permissão para usar este comando.")
        return
    # erros gerais
    await log(f"Erro slash: {error}")


# ─────────────────────────────
# Ready + sync
# ─────────────────────────────
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

    if not radar_loop.is_running():
        radar_loop.start()
    if not pulse_loop.is_running():
        pulse_loop.start()


# ─────────────────────────────
# Shutdown robusto
# ─────────────────────────────
async def shutdown(reason: str):
    await log(f"Shutdown: {reason}")
    with contextlib.suppress(Exception):
        if radar_loop.is_running():
            radar_loop.cancel()
    with contextlib.suppress(Exception):
        if pulse_loop.is_running():
            pulse_loop.cancel()

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


# ─────────────────────────────
# Entrypoint
# ─────────────────────────────
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    global HTTP_SESSION, binance, notifier
    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(limit=50)
    HTTP_SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector)

    binance = BinanceSpot(HTTP_SESSION)
    notifier = Notifier(
        client=client,
        session=HTTP_SESSION,
        telegram_enabled=bool(getattr(config, "TELEGRAM_ENABLED", True)),
        discord_alerts_channel_id=int(getattr(config, "CANAL_ALERTAS", 0) or 0),
        discord_pulse_channel_id=int(getattr(config, "CANAL_PULSO", 0) or 0),
        role_ping_id=int(getattr(config, "ROLE_PING_ID", 0) or 0),
    )

    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
