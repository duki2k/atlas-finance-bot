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

from atlas.notifier import Notifier
from atlas.binance_spot import BinanceSpot
from atlas.yahoo_data import YahooData
from atlas.engines_binance import BinanceMentorEngine
from atlas.engines_binomo import BinomoEngine
from atlas.news_engine import NewsEngine

BR_TZ = pytz.timezone("America/Sao_Paulo")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "1").strip() == "1"

intents = discord.Intents.default()

HTTP: aiohttp.ClientSession | None = None
notifier: Notifier | None = None
binance: BinanceSpot | None = None
yahoo: YahooData | None = None

engine_binance = BinanceMentorEngine()
engine_binomo = BinomoEngine()
engine_news = NewsEngine()

LOCK = asyncio.Lock()
ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)

_last_member_minute = None
_last_invest_minute = None
_last_news_minute = None
_last_binance_hour_member = None
_last_binance_hour_invest = None

# ✅ PATCH: validação do config no boot + aviso no canal de logs quando ficar READY
CONFIG_PROBLEMS: list[str] = []


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


def _now_brt() -> datetime:
    return datetime.now(BR_TZ)


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


def _should_run_member(now: datetime) -> bool:
    hhmm = now.strftime("%H:%M")
    return hhmm in set(getattr(config, "MEMBRO_TIMES", []))


def _should_run_invest(now: datetime) -> bool:
    every = int(getattr(config, "INVESTIDOR_EVERY_MINUTES", 12))
    return (now.minute % every) == 0


def _should_run_news(now: datetime) -> bool:
    every = int(getattr(config, "NEWS_EVERY_MINUTES", 30))
    return (now.minute % every) == 0


def _should_run_binance_invest_hourly(now: datetime) -> bool:
    # 1x por hora no minuto 00
    return now.minute == 0


def _test_embed(title: str, note: str) -> discord.Embed:
    now = _now_brt().strftime("%d/%m/%Y %H:%M")
    e = discord.Embed(
        title=f"✅ TESTE — {title}",
        description=f"{note}\n\n🕒 {now} BRT",
        color=0x2ECC71,
    )
    return e


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


async def _send_or_fail(channel_id: int, embed: discord.Embed, role_ping: int = 0, tag: str = "") -> tuple[bool, str]:
    if not channel_id or int(channel_id) <= 0:
        return False, f"{tag} canal_id=0"
    try:
        await notifier.send_discord(int(channel_id), embed, role_ping_id=int(role_ping or 0))
        return True, ""
    except Exception as e:
        return False, f"{tag} {e}"


# ─────────────────────────────
# LOOP BINANCE MENTOR (INV: 1x/h, MEMBRO: horários grade)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_binance_mentor():
    global _last_binance_hour_member, _last_binance_hour_invest
    if notifier is None or binance is None:
        return

    now = _now_brt()
    hour_key = now.strftime("%Y-%m-%d %H")

    async with LOCK:
        # INVESTIDOR: 1x/h
        if _should_run_binance_invest_hourly(now) and _last_binance_hour_invest != hour_key:
            picks = await engine_binance.scan_1h(binance, list(config.BINANCE_SYMBOLS))
            emb = engine_binance.build_embed(picks, tier="investidor")
            ok, err = await _send_or_fail(int(config.CANAL_BINANCE_INVESTIDOR), emb, int(config.ROLE_INVESTIDOR_ID or 0), "BINANCE_MENTOR_INV")
            if not ok:
                await log(f"Falha envio BINANCE_MENTOR_INV: {err}")
            _last_binance_hour_invest = hour_key
            await log(f"BINANCE MENTOR INVEST OK {hour_key}")

        # MEMBRO: segue a grade (4/dia normalmente)
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if _should_run_member(now) and _last_binance_hour_member != minute_key:
            picks = await engine_binance.scan_1h(binance, list(config.BINANCE_SYMBOLS))
            emb = engine_binance.build_embed(picks, tier="membro")
            ok, err = await _send_or_fail(int(config.CANAL_BINANCE_MEMBRO), emb, int(config.ROLE_MEMBRO_ID or 0), "BINANCE_MENTOR_MEMBRO")
            if not ok:
                await log(f"Falha envio BINANCE_MENTOR_MEMBRO: {err}")
            _last_binance_hour_member = minute_key
            await log(f"BINANCE MENTOR MEMBRO OK {minute_key}")


@loop_binance_mentor.error
async def loop_binance_mentor_error(err: Exception):
    await log(f"ERRO loop_binance_mentor: {err}")


# ─────────────────────────────
# LOOP BINOMO (TRADING)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_member():
    global _last_member_minute
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_member_minute == minute_key:
        return

    if not _should_run_member(now):
        # (se quiser remover log chato, comente a próxima linha)
        await log(f"MEMBRO SKIP {minute_key} (fora da grade)")
        _last_member_minute = minute_key
        return

    _last_member_minute = minute_key

    async with LOCK:
        # Binomo membro: 15m (menos spam, mais seletivo)
        entries = []
        e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
        if e15:
            entries.append(e15)
            emb2 = engine_binomo.build_embed(entries, tier="membro")
            ok2, err2 = await _send_or_fail(int(config.CANAL_BINOMO_MEMBRO), emb2, int(config.ROLE_MEMBRO_ID or 0), "BINOMO_MEMBRO")
            if not ok2:
                await log(f"Falha envio BINOMO_MEMBRO: {err2}")
        else:
            await log("MEMBRO BINOMO: sem entrada (ou mercado fechado).")

        await log(f"MEMBRO BINOMO OK {minute_key}")


@loop_member.error
async def loop_member_error(err: Exception):
    await log(f"ERRO loop_member: {err}")


@tasks.loop(minutes=1)
async def loop_investidor():
    global _last_invest_minute
    if notifier is None or yahoo is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_invest_minute == minute_key:
        return

    if not _should_run_invest(now):
        # (se quiser remover log chato, comente a próxima linha)
        await log(f"INV SKIP {minute_key} (minuto não bate)")
        _last_invest_minute = minute_key
        return

    _last_invest_minute = minute_key

    async with LOCK:
        # Binomo investidor: 1m/5m/15m (trading)
        entries = []
        for tf in ("1m", "5m", "15m"):
            e = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), tf)
            if e:
                entries.append(e)

        if entries:
            emb2 = engine_binomo.build_embed(entries, tier="investidor")
            ok2, err2 = await _send_or_fail(int(config.CANAL_BINOMO_INVESTIDOR), emb2, int(config.ROLE_INVESTIDOR_ID or 0), "BINOMO_INV")
            if not ok2:
                await log(f"Falha envio BINOMO_INV: {err2}")
        else:
            if datetime.utcnow().weekday() >= 5:
                await log("INV BINOMO: mercado fechado (fim de semana). Sem envio.")
            else:
                await log("INV BINOMO: sem entradas válidas.")

        await log(f"INV BINOMO OK {minute_key}")


@loop_investidor.error
async def loop_investidor_error(err: Exception):
    await log(f"ERRO loop_investidor: {err}")


# ─────────────────────────────
# LOOP NEWS (PT=tradução do EN base)
# ─────────────────────────────
@tasks.loop(minutes=1)
async def loop_news():
    global _last_news_minute
    if notifier is None or HTTP is None:
        return

    now = _now_brt()
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    if _last_news_minute == minute_key:
        return

    if not _should_run_news(now):
        _last_news_minute = minute_key
        return

    _last_news_minute = minute_key

    pt, en, sources, translated_ok = await engine_news.fetch(HTTP)
    engine_news.mark_seen(en)

    emb = engine_news.build_embed(pt, en, sources, translated_ok)
    ok, err = await _send_or_fail(int(config.CANAL_NEWS_CRIPTO), emb, 0, "NEWS")
    if not ok:
        await log(f"Falha envio NEWS: {err}")

    await log(f"NEWS OK {minute_key} pt={len(pt)} en={len(en)}")


@loop_news.error
async def loop_news_error(err: Exception):
    await log(f"ERRO loop_news: {err}")


# ─────────────────────────────
# COMANDOS (ADMIN)
# ─────────────────────────────
@client.tree.command(name="status", description="Status do Atlas (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"✅ Online\nGUILD={GUILD_ID or 'GLOBAL'}\n"
        f"BINANCE_MEMBRO={config.CANAL_BINANCE_MEMBRO}\nBINANCE_INV={config.CANAL_BINANCE_INVESTIDOR}\n"
        f"BINOMO_MEMBRO={config.CANAL_BINOMO_MEMBRO}\nBINOMO_INV={config.CANAL_BINOMO_INVESTIDOR}\n"
        f"NEWS={getattr(config,'CANAL_NEWS_CRIPTO',None)}\nLOGS={config.CANAL_LOGS}\n"
        f"INVESTIDOR_EVERY_MINUTES={getattr(config,'INVESTIDOR_EVERY_MINUTES',None)}\nMEMBRO_TIMES={getattr(config,'MEMBRO_TIMES',None)}",
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
    if notifier is None or binance is None or yahoo is None or HTTP is None:
        await interaction.followup.send("❌ Bot ainda iniciando.", ephemeral=True)
        return

    results = []
    fails = []

    async with LOCK:
        # Binance mentor membro
        try:
            picks = await engine_binance.scan_1h(binance, list(config.BINANCE_SYMBOLS))
            emb = engine_binance.build_embed(picks, tier="membro") if picks else _test_embed("Binance MEMBRO", "Sem picks — teste OK ✅")
            ok, err = await _send_or_fail(int(config.CANAL_BINANCE_MEMBRO), emb, int(config.ROLE_MEMBRO_ID or 0), "FORCE_BINANCE_MEMBRO")
            results.append("✅ Binance MEMBRO" if ok else f"❌ Binance MEMBRO ({err})")
        except Exception as e:
            fails.append(f"❌ Binance MEMBRO ({e})")

        # Binance mentor investidor
        try:
            picks = await engine_binance.scan_1h(binance, list(config.BINANCE_SYMBOLS))
            emb = engine_binance.build_embed(picks, tier="investidor") if picks else _test_embed("Binance INVESTIDOR", "Sem picks — teste OK ✅")
            ok, err = await _send_or_fail(int(config.CANAL_BINANCE_INVESTIDOR), emb, int(config.ROLE_INVESTIDOR_ID or 0), "FORCE_BINANCE_INV")
            results.append("✅ Binance INVESTIDOR" if ok else f"❌ Binance INVESTIDOR ({err})")
        except Exception as e:
            fails.append(f"❌ Binance INVESTIDOR ({e})")

        # Binomo membro (15m)
        try:
            entries = []
            e15 = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), "15m")
            if e15:
                entries.append(e15)
                emb2 = engine_binomo.build_embed(entries, tier="membro")
            else:
                emb2 = _test_embed("Binomo MEMBRO", "Sem entrada — teste OK ✅")
            ok, err = await _send_or_fail(int(config.CANAL_BINOMO_MEMBRO), emb2, int(config.ROLE_MEMBRO_ID or 0), "FORCE_BINOMO_MEMBRO")
            results.append("✅ Binomo MEMBRO" if ok else f"❌ Binomo MEMBRO ({err})")
        except Exception as e:
            fails.append(f"❌ Binomo MEMBRO ({e})")

        # Binomo investidor (1m/5m/15m)
        try:
            entries = []
            for tf in ("1m", "5m", "15m"):
                e = await engine_binomo.scan_timeframe(yahoo, list(config.BINOMO_TICKERS), tf)
                if e:
                    entries.append(e)
            emb3 = engine_binomo.build_embed(entries, tier="investidor") if entries else _test_embed("Binomo INVESTIDOR", "Sem entrada — teste OK ✅")
            ok, err = await _send_or_fail(int(config.CANAL_BINOMO_INVESTIDOR), emb3, int(config.ROLE_INVESTIDOR_ID or 0), "FORCE_BINOMO_INV")
            results.append("✅ Binomo INVESTIDOR" if ok else f"❌ Binomo INVESTIDOR ({err})")
        except Exception as e:
            fails.append(f"❌ Binomo INVESTIDOR ({e})")

        # News PT/EN
        try:
            pt, en, sources, translated_ok = await engine_news.fetch(HTTP)
            engine_news.mark_seen(en)
            embn = engine_news.build_embed(pt, en, sources, translated_ok) if (pt or en) else _test_embed("NEWS", "Sem news — teste OK ✅")
            ok, err = await _send_or_fail(int(getattr(config, "CANAL_NEWS_CRIPTO", 0) or 0), embn, 0, "FORCE_NEWS")
            results.append("✅ NEWS" if ok else f"❌ NEWS ({err})")
        except Exception as e:
            fails.append(f"❌ NEWS ({e})")

    await log(f"FORCE_ALL por {interaction.user} -> {results} / {fails}")
    msg = "\n".join(results + ([""] + fails if fails else []))
    await interaction.followup.send("📨 **Force All concluído:**\n" + msg, ephemeral=True)


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
    await log(f"Erro slash: {error}")


@client.event
async def on_ready():
    await log(f"READY: {client.user} (sync={SYNC_COMMANDS})")

    # ✅ PATCH: se config inválida, avisa uma vez no canal de logs
    if CONFIG_PROBLEMS:
        txt = "⚠️ CONFIG inválida detectada no boot:\n- " + "\n- ".join(CONFIG_PROBLEMS)
        await log(txt[:1800])  # evita estourar limite

    if SYNC_COMMANDS:
        await sync_commands()

    if not loop_binance_mentor.is_running():
        loop_binance_mentor.start()
    if not loop_member.is_running():
        loop_member.start()
    if not loop_investidor.is_running():
        loop_investidor.start()
    if not loop_news.is_running():
        loop_news.start()

    await log("Loops iniciados (binance_mentor/member/invest/news).")


async def shutdown(reason: str):
    await log(f"Shutdown: {reason}")

    with contextlib.suppress(Exception):
        for t in (loop_binance_mentor, loop_member, loop_investidor, loop_news):
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

    # ✅ PATCH: valida config no boot (Railway log + aviso no READY)
    global CONFIG_PROBLEMS
    try:
        validate_fn = getattr(config, "validate_config", None)
        if callable(validate_fn):
            CONFIG_PROBLEMS = list(validate_fn()) or []
            if CONFIG_PROBLEMS:
                print("CONFIG INVALIDA:\n- " + "\n- ".join(CONFIG_PROBLEMS))
        else:
            CONFIG_PROBLEMS = []
    except Exception as e:
        CONFIG_PROBLEMS = [f"Falha ao validar config: {e}"]
        print("CONFIG VALIDATION ERROR:", e)

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
