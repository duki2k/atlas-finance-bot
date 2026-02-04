# main.py
import os
import asyncio
import contextlib
import inspect
import signal
import aiohttp
import discord
import pytz
import requests
from datetime import datetime
from discord.ext import tasks
from discord import app_commands

import config
import market
import news
import telegram

# ✅ Import "signals.py" (se existir). Não derruba o bot se não existir.
try:
    import signals  # seu arquivo signals.py
except Exception as e:
    signals = None
    print(f"⚠️ signals.py não carregou: {e}")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = (os.getenv("GUILD_ID") or "").strip()
SYNC_COMMANDS = (os.getenv("SYNC_COMMANDS") or "0").strip() == "1"

BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ✅ Canal único permitido para comandos
ADMIN_CHANNEL_ID = int(getattr(config, "CANAL_ADMIN", 0) or 0)

# Controle scheduler (para não disparar 2x no mesmo dia)
ultima_manha = None
ultima_tarde = None

# Rompimento
ULTIMO_PRECO = {}      # {ativo: preco}
FALHAS_SEGUIDAS = {}   # {ativo: count}

# Anti-overlap
PUBLICACAO_LOCK = asyncio.Lock()
SINAIS_LOCK = asyncio.Lock()

# Concorrência (threads) p/ não travar o event loop com requests/feedparser
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "10"))
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

_SHUTTING_DOWN = False

# Sessão HTTP compartilhada (CoinGecko/Yahoo/Telegram etc.)
HTTP_SESSION: aiohttp.ClientSession | None = None


# ─────────────────────────────
# CHECK GLOBAL: comandos só no canal admin
# ─────────────────────────────
@tree.check
async def enforce_admin_channel(interaction: discord.Interaction) -> bool:
    # Se não configurou CANAL_ADMIN, não trava tudo sem querer
    if ADMIN_CHANNEL_ID <= 0:
        return True

    # Bloqueia DM
    if interaction.guild is None:
        raise app_commands.CheckFailure("Comandos disponíveis apenas no servidor.")

    # Trava por canal
    if interaction.channel_id != ADMIN_CHANNEL_ID:
        raise app_commands.CheckFailure(f"Use os comandos apenas em <#{ADMIN_CHANNEL_ID}>.")

    return True


# ─────────────────────────────
# Helpers
# ─────────────────────────────
def _get_cfg(name: str, default=None):
    return getattr(config, name, default)

def _channel_id(name: str):
    v = _get_cfg(name, 0)
    try:
        v = int(v)
        return v if v > 0 else None
    except Exception:
        return None

async def _maybe_await(x):
    if inspect.isawaitable(x):
        return await x
    return x

async def _call_sync_or_async(fn, *args, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(lambda: fn(*args, **kwargs))


# ─────────────────────────────
# UTIL
# ─────────────────────────────
def emoji_var(v: float) -> str:
    if v is None:
        return "⏺️"
    if v > 0:
        return "🔼"
    if v < 0:
        return "🔽"
    return "⏺️"

def sentimento_geral(qtd_altas: int, qtd_quedas: int):
    if qtd_altas > qtd_quedas:
        return "😄 Mercado positivo", 0x2ECC71
    if qtd_quedas > qtd_altas:
        return "😨 Mercado defensivo", 0xE74C3C
    return "😐 Mercado neutro", 0xF1C40F

def texto_cenario(sent_label: str) -> str:
    if "positivo" in sent_label:
        return (
            "🧭 **Cenário:** apetite por risco maior.\n"
            "✅ Foque em qualidade e tendência.\n"
            "⚠️ Cuidado com euforia / alavancagem."
        )
    if "defensivo" in sent_label:
        return (
            "🧭 **Cenário:** aversão a risco.\n"
            "🛡️ Preserve capital e liquidez.\n"
            "🎯 Entradas só com confirmação."
        )
    return (
        "🧭 **Cenário:** mercado lateral/indefinido.\n"
        "🎯 Seletividade e exposição menor.\n"
        "⏳ Aguarde direção antes de aumentar mão."
    )

def ideias_em_baixa() -> str:
    return (
        "💡 **Dia de baixa (educacional):**\n"
        "• Prefira qualidade + caixa forte\n"
        "• ETFs amplos ajudam a diversificar\n"
        "• Aportes em etapas (não tudo de uma vez)\n"
        "• Evite decisões por impulso"
    )

async def log_bot(titulo: str, mensagem: str):
    cid = _channel_id("CANAL_LOGS")
    canal = client.get_channel(cid) if cid else None
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

def dolar_para_real() -> float:
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        )
        data = r.json()
        rate = data.get("rates", {}).get("BRL")
        return float(rate) if rate else 5.0
    except Exception:
        return 5.0


# ─────────────────────────────
# ALERTA URGENTE (ROMPIMENTO)
# ─────────────────────────────
async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    cid = _channel_id("CANAL_NOTICIAS")
    canal = client.get_channel(cid) if cid else None
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    limite = float(_get_cfg("LIMITE_ROMPIMENTO_PCT", 2.0))
    var = ((preco_atual - preco_antigo) / preco_antigo) * 100.0
    if abs(var) < limite:
        return

    direcao = "🚨🔼 ROMPIMENTO DE ALTA" if var > 0 else "🚨🔽 ROMPIMENTO DE BAIXA"
    cor = 0x2ECC71 if var > 0 else 0xE74C3C

    embed = discord.Embed(
        title=direcao,
        description=f"🧷 **Ativo:** `{ativo}`\n🏷️ **Categoria:** {categoria}",
        color=cor
    )
    embed.add_field(name="Preço anterior", value=f"{preco_antigo:,.4f}", inline=True)
    embed.add_field(name="Preço atual", value=f"{preco_atual:,.4f}", inline=True)
    embed.add_field(name="Movimento", value=f"{var:+.2f}% {emoji_var(var)}", inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))

    await canal.send(embed=embed)


# ─────────────────────────────
# COLETA (não bloqueia event loop)
# ─────────────────────────────
async def _fetch_one(categoria: str, ativo: str):
    async with SEM:
        try:
            p, v = await _call_sync_or_async(market.dados_ativo, ativo)

            # FIIs: se preço não veio, ignora sem log
            if ativo.endswith("11.SA") and p is None:
                return None

            if p is None or v is None:
                FALHAS_SEGUIDAS[ativo] = FALHAS_SEGUIDAS.get(ativo, 0) + 1
                if FALHAS_SEGUIDAS[ativo] >= 3:
                    await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
                    FALHAS_SEGUIDAS[ativo] = 0
                return None

            FALHAS_SEGUIDAS[ativo] = 0
            await alerta_rompimento(ativo, float(p), categoria)
            return (ativo, float(p), float(v))

        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo} ({categoria})\n{e}")
            return None

async def coletar_dados():
    coros = []
    order = []
    for categoria, ativos in config.ATIVOS.items():
        for ativo in ativos:
            coros.append(_fetch_one(categoria, ativo))
            order.append((categoria, ativo))

    results = await asyncio.gather(*coros, return_exceptions=False)

    dados = {}
    total = 0
    for (categoria, _), item in zip(order, results):
        if not item:
            continue
        dados.setdefault(categoria, []).append(item)
        total += 1

    if total == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}
    return dados


# ─────────────────────────────
# EMBEDS
# ─────────────────────────────
def embed_relatorio(dados: dict, cot: float):
    moves = [(a, p, v) for itens in dados.values() for (a, p, v) in itens]

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, cor = sentimento_geral(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    embed = discord.Embed(
        title="📊 Relatório Completo do Mercado",
        description=f"**{sent_label}**\n\n{texto_cenario(sent_label)}",
        color=cor
    )

    embed.add_field(
        name="🔝 Top 3 Altas",
        value="\n".join([f"• `{a}` {emoji_var(v)} **{v:.2f}%**" for a, _, v in top_alta]) or "—",
        inline=False
    )
    embed.add_field(
        name="🔻 Top 3 Quedas",
        value="\n".join([f"• `{a}` {emoji_var(v)} **{v:.2f}%**" for a, _, v in top_baixa]) or "—",
        inline=False
    )

    for categoria, itens in dados.items():
        linhas = [
            f"• `{ativo}` {emoji_var(var)} **{var:.2f}%**  |  💲 {preco:,.2f}  |  🇧🇷 R$ {(preco*cot):,.2f}"
            for (ativo, preco, var) in itens
        ]
        embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.add_field(name="💡 Dica do dia", value=ideias_em_baixa(), inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))
    return embed

def embed_jornal(manchetes: list[str], periodo: str):
    embed = discord.Embed(
        title=f"🗞️ Jornal do Mercado — {periodo}",
        description="🌍 Manchetes e impacto no mercado 😄",
        color=0x00BFFF
    )

    if not manchetes:
        embed.add_field(
            name="⚠️ Sem manchetes agora",
            value="O RSS retornou vazio. Tentaremos novamente no próximo ciclo.",
            inline=False
        )
        embed.set_footer(text="Fonte: Google News RSS")
        return embed

    bloco1 = "\n".join([f"📰 **{i}.** {m}" for i, m in enumerate(manchetes[:5], start=1)])
    bloco2 = "\n".join([f"🗞️ **{i}.** {m}" for i, m in enumerate(manchetes[5:10], start=6)])

    embed.add_field(name="🔥 Manchetes principais", value=bloco1, inline=False)
    if bloco2.strip():
        embed.add_field(name="📌 Mais notícias", value=bloco2, inline=False)

    embed.add_field(
        name="🧠 Leitura rápida",
        value="• Cenário macro (juros, inflação, dólar)\n• Gestão de risco sempre ✅",
        inline=False
    )
    embed.set_footer(text="Fonte: Google News RSS")
    return embed


# ─────────────────────────────
# PUBLICAÇÕES
# ─────────────────────────────
async def enviar_publicacoes(periodo: str, *, enviar_tg=True):
    if PUBLICACAO_LOCK.locked():
        await log_bot("Scheduler", "Ignorado: execução já em andamento (anti-overlap).")
        return

    async with PUBLICACAO_LOCK:
        dados = await coletar_dados()
        if not dados:
            return

        cot = dolar_para_real()
        manchetes = await _call_sync_or_async(news.noticias) if hasattr(news, "noticias") else []

        canal_rel = client.get_channel(_channel_id("CANAL_ANALISE") or 0)
        canal_j = client.get_channel(_channel_id("CANAL_NOTICIAS") or 0)

        if canal_rel:
            await canal_rel.send(embed=embed_relatorio(dados, cot))
        else:
            await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise.")

        if canal_j and _get_cfg("NEWS_ATIVAS", True):
            await canal_j.send(embed=embed_jornal(manchetes, periodo))
        else:
            await log_bot("CANAL_NOTICIAS inválido", "Não encontrei canal de notícias ou NEWS_ATIVAS desativada.")

        if enviar_tg and hasattr(telegram, "enviar_telegram"):
            ok = await _maybe_await(telegram.enviar_telegram(f"📌 Atlas Finance — {periodo}"))
            if ok is False:
                await log_bot("Telegram", "Falha ao enviar (token/chat_id).")


# ─────────────────────────────
# SINAIS (comandos existem; execução só se signals.py suportar)
# ─────────────────────────────
async def _run_signals_now():
    if signals is None:
        return False, "signals.py não está disponível."

    for fname in ("run_now", "sinais_agora", "enviar_agora", "publicar_agora", "scan_and_post", "scan_signals"):
        fn = getattr(signals, fname, None)
        if callable(fn):
            try:
                await _call_sync_or_async(fn, client)
                return True, f"Executado via signals.{fname}()"
            except Exception as e:
                return False, f"Falha em signals.{fname}(): {e}"

    return False, "Nenhuma função compatível encontrada em signals.py."

@tree.command(name="sinaisagora", description="Força um scan/post de sinais agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_sinaisagora(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if SINAIS_LOCK.locked():
        await interaction.followup.send("⏳ Já tem um scan em andamento.", ephemeral=True)
        return
    async with SINAIS_LOCK:
        ok, msg = await _run_signals_now()
        await interaction.followup.send(("✅ " if ok else "❌ ") + msg, ephemeral=True)

@tree.command(name="sinaisstatus", description="Mostra status dos sinais (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_sinaisstatus(interaction: discord.Interaction):
    msg = (
        f"**signals.py:** `{'OK' if signals is not None else 'INDISPONÍVEL'}`\n"
        f"**SINAIS_ATIVOS (config):** `{_get_cfg('SINAIS_ATIVOS', False)}`\n"
        f"**CANAL_SINAIS_SPOT:** `{_channel_id('CANAL_SINAIS_SPOT')}`\n"
        f"**CANAL_SINAIS_FUTURES:** `{_channel_id('CANAL_SINAIS_FUTURES')}`"
    )
    await interaction.response.send_message(msg, ephemeral=True)


# ─────────────────────────────
# SLASH COMMANDS (base)
# ─────────────────────────────
@tree.command(name="testetudo", description="Testa publicações oficiais (Relatório + Jornal + Telegram) (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_testetudo(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await enviar_publicacoes("Teste Tudo (manual)", enviar_tg=True)
    await interaction.followup.send("✅ Disparei as publicações.", ephemeral=True)

@tree.command(name="reiniciar", description="Reinicia o bot (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_reiniciar(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Reiniciando...", ephemeral=True)
    await asyncio.sleep(1)
    await shutdown("manual restart")


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # ✅ Bloqueio por canal
    if isinstance(error, app_commands.CheckFailure):
        msg = str(error) or f"Use os comandos apenas em <#{ADMIN_CHANNEL_ID}>."
        if interaction.response.is_done():
            await interaction.followup.send(f"⛔ {msg}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⛔ {msg}", ephemeral=True)
        return

    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return

    with contextlib.suppress(Exception):
        await log_bot("Erro em slash command", str(error))


# ─────────────────────────────
# SCHEDULER (06h / 18h) — BRASIL
# ─────────────────────────────
@tasks.loop(minutes=1)
async def scheduler():
    global ultima_manha, ultima_tarde
    agora = datetime.now(BR_TZ)
    hhmm = agora.strftime("%H:%M")

    if hhmm == "06:00" and ultima_manha != agora.date():
        await enviar_publicacoes("Abertura (06:00)", enviar_tg=True)
        ultima_manha = agora.date()

    if hhmm == "18:00" and ultima_tarde != agora.date():
        await enviar_publicacoes("Fechamento (18:00)", enviar_tg=True)
        ultima_tarde = agora.date()


# ─────────────────────────────
# SHUTDOWN / SIGNALS
# ─────────────────────────────
async def shutdown(reason: str):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True

    with contextlib.suppress(Exception):
        if scheduler.is_running():
            scheduler.cancel()

    with contextlib.suppress(Exception):
        await log_bot("Shutdown", f"Encerrando... motivo: {reason}")

    global HTTP_SESSION
    with contextlib.suppress(Exception):
        if HTTP_SESSION is not None and not HTTP_SESSION.closed:
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
# READY + SYNC (CORRIGIDO ✅)
# ─────────────────────────────
@client.event
async def on_ready():
    print(f"🤖 Conectado como {client.user}")
    local_names = [c.name for c in tree.get_commands()]
    print("COMANDOS REGISTRADOS (local):", local_names)

    if SYNC_COMMANDS:
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
                print(f"✅ Sync GUILD OK ({GUILD_ID}). Publicados:", [c.name for c in synced])
            else:
                synced = await tree.sync()
                print("✅ Sync GLOBAL OK. Publicados:", [c.name for c in synced])
        except Exception as e:
            print(f"⚠️ Falha ao sincronizar slash commands: {e}")

    if not scheduler.is_running():
        scheduler.start()


# ─────────────────────────────
# ENTRYPOINT ROBUSTO
# ─────────────────────────────
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    global HTTP_SESSION
    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(limit=50)
    HTTP_SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector)

    market.set_session(HTTP_SESSION)
    news.set_session(HTTP_SESSION)
    telegram.set_session(HTTP_SESSION)

    async with client:
        try:
            await client.start(TOKEN)
        finally:
            with contextlib.suppress(Exception):
                if HTTP_SESSION is not None and not HTTP_SESSION.closed:
                    await HTTP_SESSION.close()

if __name__ == "__main__":
    asyncio.run(main())
