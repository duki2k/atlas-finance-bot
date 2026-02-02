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

# Controle scheduler (para não disparar 2x no mesmo dia)
ultima_manha = None
ultima_tarde = None

# Rompimento
ULTIMO_PRECO = {}      # {ativo: preco}
FALHAS_SEGUIDAS = {}   # {ativo: count}


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

async def log_bot(titulo: str, mensagem: str):
    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)


# ─────────────────────────────
# ALERTA URGENTE (ROMPIMENTO)
# ─────────────────────────────

async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    canal = bot.get_channel(config.CANAL_NOTICIAS)
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
# COLETA EM LOTES
# ─────────────────────────────

async def coletar_lote(categoria: str, ativos: list[str], delay: float = 0.35):
    itens = []

    for ativo in ativos:
        try:
            p, v = market.dados_ativo(ativo)

            # FIIs: se preço não veio, não loga, só pula
            if ativo.endswith("11.SA") and p is None:
                await asyncio.sleep(delay)
                continue

            if p is None or v is None:
                # reduz spam: só loga se falhar 3 vezes seguidas
                FALHAS_SEGUIDAS[ativo] = FALHAS_SEGUIDAS.get(ativo, 0) + 1
                if FALHAS_SEGUIDAS[ativo] >= 3:
                    await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
                    FALHAS_SEGUIDAS[ativo] = 0
                await asyncio.sleep(delay)
                continue

            FALHAS_SEGUIDAS[ativo] = 0
            itens.append((ativo, p, v))

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

def embed_relatorio(dados: dict, cot: float):
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, preco, var))

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
        linhas = []
        for ativo, preco, var in itens:
            linhas.append(
                f"• `{ativo}` {emoji_var(var)} **{var:.2f}%**  |  💲 {preco:,.2f}  |  🇧🇷 R$ {(preco*cot):,.2f}"
            )
        embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.add_field(name="💡 Dica do dia", value=ideias_em_baixa(), inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))
    return embed


def embed_jornal(manchetes: list[str], periodo: str):
    embed = discord.Embed(
        title=f"🗞️ Jornal do Mercado — {periodo}",
        description="🌍 Manchetes e impacto no mercado (mais leve, estilo jornal 😄)",
        color=0x00BFFF
    )

    if not manchetes:
        embed.add_field(
            name="⚠️ Sem manchetes agora",
            value="O RSS retornou vazio neste momento. Tentaremos novamente no próximo ciclo.",
            inline=False
        )
        embed.set_footer(text="Fonte: Google News RSS")
        return embed

    # separação em blocos (mais “jornal”)
    bloco1 = "\n".join([f"📰 **{i}.** {m}" for i, m in enumerate(manchetes[:5], start=1)])
    bloco2 = "\n".join([f"🗞️ **{i}.** {m}" for i, m in enumerate(manchetes[5:10], start=6)])

    embed.add_field(name="🔥 Manchetes principais", value=bloco1, inline=False)
    if bloco2.strip():
        embed.add_field(name="📌 Mais notícias", value=bloco2, inline=False)

    embed.add_field(
        name="🧠 Leitura rápida",
        value="• Considere o cenário macro (juros, inflação, dólar)\n• Evite impulso\n• Gestão de risco sempre ✅",
        inline=False
    )
    embed.set_footer(text="Fonte: Google News RSS")
    return embed


def telegram_resumo(dados: dict, manchetes: list[str], periodo: str):
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, preco, var))

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
# PUBLICAÇÕES
# ─────────────────────────────

async def enviar_publicacoes(periodo: str, *, canal_relatorio_id=None, canal_jornal_id=None, enviar_tg=True):
    dados = await coletar_dados()
    if not dados:
        return

    cot = dolar_para_real()
    manchetes = news.noticias()

    canal_rel = bot.get_channel(canal_relatorio_id or config.CANAL_ANALISE)
    canal_j = bot.get_channel(canal_jornal_id or config.CANAL_NOTICIAS)

    if canal_rel:
        await canal_rel.send(embed=embed_relatorio(dados, cot))
    else:
        await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise.")

    if canal_j and config.NEWS_ATIVAS:
        await canal_j.send(embed=embed_jornal(manchetes, periodo))
    else:
        await log_bot("CANAL_NOTICIAS inválido", "Não encontrei canal de notícias ou NEWS_ATIVAS desativada.")

    if enviar_tg:
        ok = telegram.enviar_telegram(telegram_resumo(dados, manchetes, periodo))
        if not ok:
            await log_bot("Telegram", "Falha ao enviar (verifique TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID).")

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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar este comando.")
        return
    await log_bot("Erro em comando", str(error))

@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance — Comandos (Admin)",
        description="Testes separados por canal + Telegram",
        color=0x5865F2
    )
    embed.add_field(
        name="🧪 Testes (Discord no canal atual)",
        value=(
            "`!testrelatorio` → envia relatório aqui\n"
            "`!testjornal` → envia jornal aqui\n"
            "`!testtudo` → relatório+jornal aqui (sem mexer nos canais oficiais)"
        ),
        inline=False
    )
    embed.add_field(
        name="📌 Testes (canais oficiais)",
        value="`!testarpublicacoes` → dispara nos canais oficiais + Telegram",
        inline=False
    )
    embed.add_field(
        name="📨 Testes (Telegram)",
        value="`!testtelegram` → manda resumo no Telegram",
        inline=False
    )
    embed.add_field(
        name="🚨 Testes (Urgente)",
        value="`!testrompimento` → simula alerta urgente no canal de notícias",
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
    try:
        await ctx.send(embed=embed_jornal(manchetes, "Teste (canal atual)"))
    except discord.Forbidden:
        await ctx.send("⚠️ Falta permissão **Embed Links** neste canal. Vou mandar em texto:")
        await ctx.send("\n".join([f"📰 {m}" for m in manchetes[:10]]) if manchetes else "Sem manchetes.")
        await log_bot("Permissão", f"Faltando Embed Links no canal {ctx.channel.id}")

@bot.command()
@commands.has_permissions(administrator=True)
async def testtudo(ctx):
    await ctx.send("🧪 Enviando relatório + jornal neste canal (sem Telegram)...")
    await enviar_publicacoes("Teste (canal atual)", canal_relatorio_id=ctx.channel.id, canal_jornal_id=ctx.channel.id, enviar_tg=False)
    await ctx.send("✅ OK")

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
async def testarpublicacoes(ctx):
    await ctx.send("🧪 Disparando publicações nos canais oficiais + Telegram...")
    await enviar_publicacoes("Teste Manual")
    await ctx.send("✅ Teste finalizado")

@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()


# ─────────────────────────────
# SCHEDULER (06h / 18h) — BRASIL
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultima_manha, ultima_tarde
    agora = datetime.now(BR_TZ)
    hhmm = agora.strftime("%H:%M")

    if hhmm == "06:00" and ultima_manha != agora.date():
        await enviar_publicacoes("Abertura (06:00)")
        ultima_manha = agora.date()

    if hhmm == "18:00" and ultima_tarde != agora.date():
        await enviar_publicacoes("Fechamento (18:00)")
        ultima_tarde = agora.date()


bot.run(TOKEN)
