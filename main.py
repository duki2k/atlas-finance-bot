# main.py
import os
import asyncio
import discord
import pytz
import aiohttp
from datetime import datetime
from discord.ext import tasks
from discord import app_commands
from typing import Optional

import config
import market
import news
import telegram

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

# Slash-only: sem message_content
intents = discord.Intents.default()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Controle scheduler (para não disparar 2x no mesmo dia)
ultima_manha = None
ultima_tarde = None

# Rompimento (funcionalidade continua ativa)
ULTIMO_PRECO = {}      # {ativo: preco}
FALHAS_SEGUIDAS = {}   # {ativo: count}

# HTTP session + cache FX
HTTP: Optional[aiohttp.ClientSession] = None
_FX_CACHE = {"rate": 5.0, "ts": 0.0}
_FX_TTL = 600  # 10 min

# Locks anti-overlap
PUBLICACAO_LOCK = asyncio.Lock()

# Concorrência de coleta
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

# Sync do tree
_TREE_SYNCED = False

# ✅ Sync opcional (pra boot rápido)
SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "0") == "1"


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
    canal = client.get_channel(config.CANAL_LOGS)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

async def dolar_para_real_async() -> float:
    global _FX_CACHE, HTTP
    now = asyncio.get_event_loop().time()

    if (now - _FX_CACHE["ts"]) < _FX_TTL and _FX_CACHE["rate"] > 0:
        return float(_FX_CACHE["rate"])

    if HTTP is None:
        return float(_FX_CACHE.get("rate") or 5.0)

    url = "https://api.exchangerate.host/latest"
    params = {"base": "USD", "symbols": "BRL"}

    try:
        async with HTTP.get(url, params=params, timeout=10) as r:
            r.raise_for_status()
            data = await r.json()
            rate = data.get("rates", {}).get("BRL")
            rate = float(rate) if rate else 5.0
            _FX_CACHE = {"rate": rate, "ts": now}
            return rate
    except Exception:
        return float(_FX_CACHE.get("rate") or 5.0)


# ─────────────────────────────
# ALERTA AUTOMÁTICO (ROMPIMENTO)
# ─────────────────────────────

async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    canal = client.get_channel(config.CANAL_NOTICIAS)
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    var = ((preco_atual - preco_antigo) / preco_antigo) * 100.0
    if abs(var) < float(config.LIMITE_ROMPIMENTO_PCT):
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
# COLETA CONCORRENTE
# ─────────────────────────────

async def _fetch_one(categoria: str, ativo: str):
    async with SEM:
        try:
            p, v = await market.dados_ativo(ativo)

            # FIIs: se preço não veio, não loga, só ignora
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
# EMBEDS + TELEGRAM
# ─────────────────────────────

def embed_relatorio(dados: dict, cot: float):
    moves = [(ativo, preco, var) for itens in dados.values() for (ativo, preco, var) in itens]

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

def embed_jornal(manchetes: list, periodo: str):
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

def telegram_resumo(dados: dict, manchetes: list, periodo: str):
    moves = [(ativo, preco, var) for itens in dados.values() for (ativo, preco, var) in itens]

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, _ = sentimento_geral(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    linhas = []
    linhas.append(f"📊 Resumo do Mercado — {periodo}")
    linhas.append(f"{sent_label}")
    linhas.append("")
    linhas.append(texto_cenario(sent_label))
    linhas.append("")
    linhas.append("🔝 Top 3 Altas")
    linhas.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_alta] or ["- —"])
    linhas.append("")
    linhas.append("🔻 Top 3 Quedas")
    linhas.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_baixa] or ["- —"])
    linhas.append("")
    linhas.append("🌍 Manchetes do Mundo")
    if manchetes:
        for m in manchetes[:6]:
            linhas.append(f"📰 {m}")
    else:
        linhas.append("📰 (sem manchetes disponíveis agora)")
    linhas.append("")
    linhas.append(ideias_em_baixa())
    linhas.append("")
    linhas.append("— Atlas Finance")
    return "\n".join(linhas)


# ─────────────────────────────
# PUBLICAÇÕES (COM LOCK)
# ─────────────────────────────

async def enviar_publicacoes(periodo: str, *, enviar_tg=True):
    if PUBLICACAO_LOCK.locked():
        await log_bot("Scheduler", "Ignorado: execução já em andamento (anti-overlap).")
        return

    async with PUBLICACAO_LOCK:
        dados = await coletar_dados()
        if not dados:
            return

        cot = await dolar_para_real_async()
        manchetes = await news.noticias()

        canal_rel = client.get_channel(config.CANAL_ANALISE)
        canal_j = client.get_channel(config.CANAL_NOTICIAS)

        if canal_rel:
            await canal_rel.send(embed=embed_relatorio(dados, cot))
        else:
            await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise.")

        if canal_j and config.NEWS_ATIVAS:
            await canal_j.send(embed=embed_jornal(manchetes, periodo))
        else:
            await log_bot("CANAL_NOTICIAS inválido", "Não encontrei canal de notícias ou NEWS_ATIVAS desativada.")

        if enviar_tg:
            ok = await telegram.enviar_telegram(telegram_resumo(dados, manchetes, periodo))
            if not ok:
                await log_bot("Telegram", "Falha ao enviar (token/chat_id).")

        if not manchetes:
            await log_bot("RSS vazio", "news.noticias() retornou lista vazia (pode ser temporário).")


# ─────────────────────────────
# READY + SYNC SLASH COMMANDS
# ─────────────────────────────

@client.event
async def on_ready():
    global HTTP, _TREE_SYNCED
    print(f"🤖 Conectado como {client.user}")

    if HTTP is None:
        timeout = aiohttp.ClientTimeout(total=12, connect=3, sock_read=8)
        connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENCY, ttl_dns_cache=300)
        HTTP = aiohttp.ClientSession(timeout=timeout, connector=connector)

        market.set_session(HTTP)
        news.set_session(HTTP)
        telegram.set_session(HTTP)

    # ✅ Sync opcional: só quando você quiser (boot mais rápido)
    if (not _TREE_SYNCED) and SYNC_COMMANDS:
        try:
            gid = os.getenv("GUILD_ID")
            if gid:
                guild = discord.Object(id=int(gid))
                await tree.sync(guild=guild)
                print(f"✅ Slash commands sincronizados no servidor {gid}")
            else:
                await tree.sync()
                print("✅ Slash commands sincronizados globalmente")
            _TREE_SYNCED = True
        except Exception as e:
            print(f"⚠️ Falha ao sincronizar slash commands: {e}")

    if not scheduler.is_running():
        scheduler.start()


# ─────────────────────────────
# SLASH COMMANDS (somente 2)
# ─────────────────────────────

@tree.command(
    name="testetudo",
    description="Testa todas as publicações oficiais (Relatório + Jornal + Telegram) (Admin)"
)
@app_commands.checks.has_permissions(administrator=True)
async def slash_testetudo(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await enviar_publicacoes("Teste Tudo (manual)", enviar_tg=True)
    await interaction.followup.send("✅ Disparei todas as publicações oficiais (Discord + Telegram).", ephemeral=True)

@tree.command(name="reiniciar", description="Reinicia o bot (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_reiniciar(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Reiniciando AGORA...", ephemeral=True)

    # Para scheduler antes de matar o processo
    try:
        scheduler.stop()
    except Exception:
        pass

    # Fecha HTTP sem travar
    global HTTP
    try:
        if HTTP is not None:
            await HTTP.close()
            HTTP = None
    except Exception:
        pass

    # Delay curto pra garantir que a resposta foi enviada
    await asyncio.sleep(1.0)

    # ⚡ FORÇA restart no Railway (exit code != 0)
    os._exit(1)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return
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


client.run(TOKEN)
