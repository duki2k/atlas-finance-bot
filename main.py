# main.py
import os
import asyncio
import discord
import requests
import pytz
from datetime import datetime
from discord.ext import commands, tasks

import config
import market
import news
import telegram

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Scheduler controle
ultimo_manha = None
ultimo_tarde = None

# Rompimento
ULTIMO_PRECO = {}  # {ativo: preco}
FALHAS_SEGUIDAS = {}  # {ativo: count} -> para reduzir spam no log


# ─────────────────────────────
# UTIL
# ─────────────────────────────

def dolar_para_real():
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        ).json()
        return float(r["rates"]["BRL"])
    except Exception:
        return 5.0


async def log_bot(titulo, mensagem):
    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)


def emoji_var(v: float):
    if v is None:
        return "⏺️"
    if v > 0:
        return "🔼"
    if v < 0:
        return "🔽"
    return "⏺️"


def sentimento(altas, quedas):
    if altas > quedas:
        return "😄 Mercado positivo", 0x2ECC71
    if quedas > altas:
        return "😨 Mercado defensivo", 0xE74C3C
    return "😐 Mercado neutro", 0xF1C40F


def texto_cenario(sent_label):
    if "positivo" in sent_label:
        return (
            "🧭 Cenário: apetite por risco maior.\n"
            "✅ Foque em qualidade e tendência.\n"
            "⚠️ Evite exagerar na alavancagem."
        )
    if "defensivo" in sent_label:
        return (
            "🧭 Cenário: aversão a risco.\n"
            "🛡️ Priorize proteção e liquidez.\n"
            "🎯 Entradas só com confirmação."
        )
    return (
        "🧭 Cenário: mercado lateral/indefinido.\n"
        "🎯 Seletividade e posição menor.\n"
        "⏳ Espere direção antes de aumentar exposição."
    )


def ideias_em_baixa_educacional():
    return (
        "💡 Se o dia estiver em baixa (educacional):\n"
        "• Prefira qualidade e empresas resilientes\n"
        "• Use ETFs amplos para diversificar\n"
        "• Setores defensivos (consumo básico, saúde)\n"
        "• Faça aportes em etapas (não tudo de uma vez)\n"
        "• Preserve liquidez e evite impulso"
    )


# ─────────────────────────────
# ROMPIMENTO URGENTE
# ─────────────────────────────

async def alerta_rompimento(ativo, preco_atual, categoria):
    canal = bot.get_channel(config.CANAL_NOTICIAS)
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    variacao = ((preco_atual - preco_antigo) / preco_antigo) * 100
    if abs(variacao) < float(config.LIMITE_ROMPIMENTO_PCT):
        return

    direcao = "🚨🔼 ROMPIMENTO DE ALTA" if variacao > 0 else "🚨🔽 ROMPIMENTO DE BAIXA"
    cor = 0x2ECC71 if variacao > 0 else 0xE74C3C

    embed = discord.Embed(
        title=direcao,
        description=f"Ativo: **{ativo}**\nCategoria: **{categoria}**",
        color=cor
    )
    embed.add_field(name="Preço anterior", value=f"{preco_antigo:,.4f}", inline=True)
    embed.add_field(name="Preço atual", value=f"{preco_atual:,.4f}", inline=True)
    embed.add_field(name="Movimento", value=f"{variacao:+.2f}%", inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))

    await canal.send(embed=embed)


# ─────────────────────────────
# COLETA EM LOTES
# ─────────────────────────────

async def coletar_lote(categoria, ativos, delay=0.35):
    itens = []

    for ativo in ativos:
        try:
            p, v = market.dados_ativo(ativo)

            # FIIs: se preço não veio, pula sem log
            if ativo.endswith("11.SA") and p is None:
                continue

            if p is None or v is None:
                # reduz spam: só loga se falhar 3 vezes seguidas
                FALHAS_SEGUIDAS[ativo] = FALHAS_SEGUIDAS.get(ativo, 0) + 1
                if FALHAS_SEGUIDAS[ativo] >= 3:
                    await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
                    FALHAS_SEGUIDAS[ativo] = 0
                await asyncio.sleep(delay)
                continue

            # reset falhas
            FALHAS_SEGUIDAS[ativo] = 0

            itens.append((ativo, p, v))

            # alerta rompimento
            await alerta_rompimento(ativo, p, categoria)

        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo} ({categoria})\n{e}")

        await asyncio.sleep(delay)

    return itens


async def coletar_dados():
    dados = {}
    total = 0

    for categoria, ativos in config.ATIVOS.items():
        lote = await coletar_lote(categoria, ativos)
        if lote:
            dados[categoria] = lote
            total += len(lote)

    if total == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}

    return dados


# ─────────────────────────────
# EMBEDS
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, preco, var))

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, cor = sentimento(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    embed = discord.Embed(
        title="📊 Relatório Completo do Mercado",
        description=f"{sent_label}\n\n{texto_cenario(sent_label)}",
        color=cor
    )

    embed.add_field(
        name="🔝 Top 3 Altas",
        value="\n".join(f"• `{a}` {emoji_var(v)} {v:.2f}%" for a, _, v in top_alta) if top_alta else "—",
        inline=False
    )
    embed.add_field(
        name="🔻 Top 3 Quedas",
        value="\n".join(f"• `{a}` {emoji_var(v)} {v:.2f}%" for a, _, v in top_baixa) if top_baixa else "—",
        inline=False
    )

    for categoria, itens in dados.items():
        linhas = []
        for ativo, preco, var in itens:
            linhas.append(
                f"`{ativo}` {emoji_var(var)} {var:.2f}%  |  💲 {preco:,.2f}  |  🇧🇷 R$ {(preco*cotacao):,.2f}"
            )
        embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.set_footer(text="Atlas Finance • Dados com fallback + cache")
    return embed


def embed_jornal(manchetes, periodo):
    embed = discord.Embed(
        title=f"🗞️ Jornal do Mercado — {periodo}",
        description="🌍 Principais manchetes e impactos no mercado",
        color=0x00BFFF
    )

    if manchetes:
        blocos = []
        for i, n in enumerate(manchetes[:10], start=1):
            blocos.append(f"📰 **{i}.** {n}")
        embed.add_field(name="🔥 Manchetes (Mundo)", value="\n\n".join(blocos), inline=False)
    else:
        embed.add_field(
            name="⚠️ Sem manchetes agora",
            value="O RSS retornou vazio neste momento. Tentaremos novamente no próximo ciclo.",
            inline=False
        )

    embed.set_footer(text="Fonte: Google News RSS")
    return embed


def telegram_resumo(dados, manchetes, periodo):
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, preco, var))

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, _ = sentimento(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    txt = []
    txt.append(f"📊 Resumo do Mercado — {periodo}")
    txt.append(f"{sent_label}")
    txt.append("")
    txt.append(texto_cenario(sent_label))
    txt.append("")

    txt.append("🔝 Top 3 Altas")
    txt.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_alta] or ["- —"])
    txt.append("")

    txt.append("🔻 Top 3 Quedas")
    txt.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_baixa] or ["- —"])
    txt.append("")

    txt.append("🌍 Manchetes do Mundo")
    if manchetes:
        for n in manchetes[:6]:
            txt.append(f"📰 {n}")
    else:
        txt.append("📰 (sem manchetes disponíveis agora)")
    txt.append("")

    txt.append(ideias_em_baixa_educacional())
    txt.append("")
    txt.append("— Atlas Finance")

    return "\n".join(txt)


# ─────────────────────────────
# PUBLICAÇÕES
# ─────────────────────────────

async def enviar_publicacoes(periodo, canal_relatorio=None, canal_jornal=None, enviar_tg=True):
    dados = await coletar_dados()
    if not dados:
        return

    cot = dolar_para_real()
    manchetes = news.noticias()

    # Discord relatório
    canal_rel = canal_relatorio or bot.get_channel(config.CANAL_ANALISE)
    if canal_rel:
        await canal_rel.send(embed=embed_relatorio(dados, cot))
    else:
        await log_bot("CANAL_ANALISE inválido", "Não encontrei o canal de análise.")

    # Discord jornal
    canal_j = canal_jornal or bot.get_channel(config.CANAL_NOTICIAS)
    if canal_j:
        await canal_j.send(embed=embed_jornal(manchetes, periodo))
    else:
        await log_bot("CANAL_NOTICIAS inválido", "Não encontrei o canal de notícias.")

    # Telegram
    if enviar_tg:
        ok = telegram.enviar_telegram(telegram_resumo(dados, manchetes, periodo))
        if not ok:
            await log_bot("Telegram", "Falha ao enviar (verifique TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID).")

    # Log de RSS vazio
    if not manchetes:
        await log_bot("RSS vazio", "news.noticias() retornou lista vazia (pode ser temporário).")


# ─────────────────────────────
# COMANDOS (ADMIN ONLY)
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    if not scheduler.is_running():
        scheduler.start()

@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance — Comandos (Admin)",
        description="Testes separados por canal + Telegram",
        color=0x5865F2
    )
    embed.add_field(
        name="🧪 Testes (Discord)",
        value=(
            "`!testrelatorio` → envia relatório neste canal\n"
            "`!testjornal` → envia jornal neste canal\n"
            "`!testtudo` → relatório + jornal neste canal (sem mexer nos canais oficiais)"
        ),
        inline=False
    )
    embed.add_field(
        name="📨 Testes (Telegram)",
        value="`!testtelegram` → envia um resumo no Telegram",
        inline=False
    )
    embed.add_field(
        name="🚨 Testes (Rompimento)",
        value="`!testrompimento` → simula alerta urgente no canal de notícias",
        inline=False
    )
    embed.add_field(
        name="⏱️ Publicações oficiais",
        value="Automático 06:00 e 18:00 (Discord + Telegram)",
        inline=False
    )
    embed.add_field(
        name="⚙️ Sistema",
        value="`!reiniciar` → reinicia o bot",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def testrelatorio(ctx):
    await ctx.send("🧪 Gerando relatório aqui...")
    dados = await coletar_dados()
    if not dados:
        await ctx.send("❌ Não consegui coletar dados.")
        return
    cot = dolar_para_real()
    await ctx.send(embed=embed_relatorio(dados, cot))

@bot.command()
@commands.has_permissions(administrator=True)
async def testjornal(ctx):
    await ctx.send("🧪 Gerando jornal aqui...")
    manchetes = news.noticias()
    await ctx.send(embed=embed_jornal(manchetes, "Teste (canal atual)"))

@bot.command()
@commands.has_permissions(administrator=True)
async def testtudo(ctx):
    await ctx.send("🧪 Enviando relatório + jornal neste canal...")
    await enviar_publicacoes("Teste (canal atual)", canal_relatorio=ctx.channel, canal_jornal=ctx.channel, enviar_tg=False)
    await ctx.send("✅ OK (sem Telegram)")

@bot.command()
@commands.has_permissions(administrator=True)
async def testtelegram(ctx):
    await ctx.send("🧪 Enviando teste no Telegram...")
    dados = await coletar_dados()
    if not dados:
        await ctx.send("❌ Não consegui coletar dados.")
        return
    manchetes = news.noticias()
    ok = telegram.enviar_telegram(telegram_resumo(dados, manchetes, "Teste Telegram"))
    await ctx.send("✅ Telegram enviado" if ok else "❌ Falha no Telegram (token/chat_id)")

@bot.command()
@commands.has_permissions(administrator=True)
async def testrompimento(ctx):
    canal = bot.get_channel(config.CANAL_NOTICIAS)
    if not canal:
        await ctx.send("❌ CANAL_NOTICIAS inválido.")
        return

    embed = discord.Embed(
        title="🚨🔼 ROMPIMENTO DE ALTA (TESTE)",
        description="Simulação de alerta urgente",
        color=0x2ECC71
    )
    embed.add_field(name="Ativo", value="TESTE", inline=True)
    embed.add_field(name="Movimento", value="+2.50%", inline=True)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))

    await canal.send(embed=embed)
    await ctx.send("✅ Rompimento teste enviado no canal de notícias")

@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()

# ─────────────────────────────
# SCHEDULER 06h/18h
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_manha, ultimo_tarde
    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_manha != agora.date():
        await enviar_publicacoes("Abertura (06:00)")
        ultimo_manha = agora.date()

    if hora == "18:00" and ultimo_tarde != agora.date():
        await enviar_publicacoes("Fechamento (18:00)")
        ultimo_tarde = agora.date()

bot.run(TOKEN)
