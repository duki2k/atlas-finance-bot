import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
import requests
from datetime import time, datetime
import pytz

# ─────────────────────────────
# CONFIGURAÇÕES BÁSICAS
# ─────────────────────────────

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ─────────────────────────────
# MAPA DE ATIVOS (NOME COMPLETO + TIPO)
# ─────────────────────────────

ATIVOS_INFO = {
    # Ações
    "AAPL": ("Apple Inc.", "Ação EUA"),
    "MSFT": ("Microsoft Corporation", "Ação EUA"),
    "AMZN": ("Amazon.com Inc.", "Ação EUA"),
    "GOOGL": ("Alphabet Inc. (Google)", "Ação EUA"),
    "TSLA": ("Tesla Inc.", "Ação EUA"),
    "NVDA": ("NVIDIA Corporation", "Ação EUA"),
    "META": ("Meta Platforms Inc.", "Ação EUA"),
    "BRK-B": ("Berkshire Hathaway Inc.", "Ação EUA"),
    "JPM": ("JPMorgan Chase & Co.", "Ação EUA"),
    "V": ("Visa Inc.", "Ação EUA"),
    "MA": ("Mastercard Inc.", "Ação EUA"),

    # Criptomoedas
    "BTC-USD": ("Bitcoin", "Criptomoeda"),
    "ETH-USD": ("Ethereum", "Criptomoeda"),
    "SOL-USD": ("Solana", "Criptomoeda"),
    "ADA-USD": ("Cardano", "Criptomoeda"),
    "XRP-USD": ("XRP", "Criptomoeda"),
    "BNB-USD": ("Binance Coin", "Criptomoeda"),
}

# ─────────────────────────────
# FUNÇÕES AUXILIARES
# ─────────────────────────────

def admin_channel_only(ctx):
    return config.CANAL_ADMIN and ctx.channel.id == config.CANAL_ADMIN

def dolar_para_real():
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        ).json()
        return float(r["rates"]["BRL"])
    except:
        return 5.0  # fallback seguro

def sentimento_mercado(noticias):
    texto = " ".join(noticias).lower()
    positivas = ["alta", "sobe", "ganho", "avanço", "recuperação", "otimismo"]
    negativas = ["queda", "cai", "crise", "tensão", "volatilidade", "inflação"]

    score = sum(p in texto for p in positivas) - sum(n in texto for n in negativas)

    if score >= 2:
        return "🟢 **Positivo** — mercado com viés construtivo"
    elif score <= -2:
        return "🔴 **Defensivo** — cautela e proteção de capital"
    return "🟡 **Neutro** — mercado indefinido"

# ─────────────────────────────
# EMBED ÚNICO — RELATÓRIO DE ATIVOS
# ─────────────────────────────

def embed_relatorio_geral(dados, cotacao):
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y às %H:%M")

    embed = discord.Embed(
        title="📊 Relatório Diário de Ativos",
        description="Panorama consolidado dos principais ativos do mercado",
        color=0x1ABC9C
    )

    acoes = []
    criptos = []

    for ativo, preco_usd in dados.items():
        preco_brl = preco_usd * cotacao
        nome, tipo = ATIVOS_INFO.get(ativo, (ativo, "Ativo Financeiro"))

        linha = (
            f"**{nome}** (`{ativo}`)\n"
            f"💲 ${preco_usd:,.2f}  |  🇧🇷 R$ {preco_brl:,.2f}"
        )

        if ativo.endswith("-USD"):
            criptos.append(linha)
        else:
            acoes.append(linha)

    if acoes:
        embed.add_field(
            name="📈 Ações",
            value="\n\n".join(acoes),
            inline=False
        )

    if criptos:
        embed.add_field(
            name="🪙 Criptomoedas",
            value="\n\n".join(criptos),
            inline=False
        )

    embed.set_footer(text=f"Atlas Community ® 2026 • Atualizado em {agora}")
    return embed

# ─────────────────────────────
# EMBED — JORNAL DO MERCADO (VISUAL MELHORADO)
# ─────────────────────────────

def embed_jornal(noticias):
    embed = discord.Embed(
        title="🗞️ Jornal do Mercado Global",
        description="Resumo das principais notícias econômicas e financeiras",
        color=0xF39C12
    )

    noticias_formatadas = []
    for i, n in enumerate(noticias[:6], start=1):
        noticias_formatadas.append(f"**{i}.** {n}")

    embed.add_field(
        name="🌍 Destaques do Dia",
        value="\n\n".join(noticias_formatadas),
        inline=False
    )

    embed.add_field(
        name="📊 Sentimento do Mercado",
        value=sentimento_mercado(noticias),
        inline=False
    )

    embed.add_field(
        name="🧠 Leitura do Bot",
        value=(
            "• Evite decisões impulsivas\n"
            "• Priorize gestão de risco\n"
            "• Confirme tendências antes de operar"
        ),
        inline=False
    )

    embed.set_footer(text="Atlas Community ® 2026")
    return embed

# ─────────────────────────────
# EVENTO READY
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")

    if not analise_diaria.is_running():
        analise_diaria.start()

    if not noticias_diarias.is_running():
        noticias_diarias.start()

    if not resumo_semanal.is_running():
        resumo_semanal.start()

# ─────────────────────────────
# COMANDOS (ADMIN ONLY)
# ─────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def help(ctx):
    if not admin_channel_only(ctx):
        return

    embed = discord.Embed(
        title="🤖 Atlas Finance Bot — Painel Admin",
        color=0x3498DB
    )

    embed.add_field(
        name="⚙️ Configuração",
        value="`!setcanal`\n`!setcanalnoticias`\n`!setcanaladmin`",
        inline=False
    )

    embed.add_field(
        name="🧪 Testes / Status",
        value="`!testenoticias`\n`!testarpublicacoes`\n`!statusbot`",
        inline=False
    )

    embed.add_field(
        name="📊 Automático",
        value=(
            "• Relatório diário de ativos (06h)\n"
            "• Jornal do mercado (06h e 18h)\n"
            "• Resumo semanal (sexta 18h)"
        ),
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanal(ctx):
    config.CANAL_ANALISE = ctx.channel.id
    await ctx.send("✅ Canal de análises definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanalnoticias(ctx):
    config.CANAL_NOTICIAS = ctx.channel.id
    await ctx.send("📰 Canal de notícias definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanaladmin(ctx):
    config.CANAL_ADMIN = ctx.channel.id
    await ctx.send("🔒 Canal admin definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def testenoticias(ctx):
    if not admin_channel_only(ctx):
        return

    noticias = news.noticias()
    if not noticias:
        await ctx.send("❌ Nenhuma notícia retornada")
        return

    await ctx.send(embed=embed_jornal(noticias))

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    if not admin_channel_only(ctx):
        return

    await ctx.send("🧪 Disparo manual iniciado")
    await analise_diaria()
    await noticias_diarias()
    await ctx.send("✅ Publicações enviadas")

@bot.command()
@commands.has_permissions(administrator=True)
async def statusbot(ctx):
    if not admin_channel_only(ctx):
        return

    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(title="📡 Status do Bot", color=0x2ECC71)
    embed.add_field(name="Bot", value=str(bot.user), inline=False)
    embed.add_field(name="Horário", value=agora, inline=True)
    embed.add_field(name="Notícias", value="Ativas" if config.NEWS_ATIVAS else "Off", inline=True)
    await ctx.send(embed=embed)

# ─────────────────────────────
# TASKS AUTOMÁTICAS
# ─────────────────────────────

@tasks.loop(time=time(hour=6, minute=0, tzinfo=BR_TZ))
async def analise_diaria():
    if not config.CANAL_ANALISE:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    cotacao = dolar_para_real()

    dados = {}
    for ativo in config.ATIVOS:
        try:
            dados[ativo] = market.preco_atual(ativo)
        except:
            pass

    if not dados:
        return

    await canal.send(embed=embed_relatorio_geral(dados, cotacao))

@tasks.loop(time=[
    time(hour=6, minute=0, tzinfo=BR_TZ),
    time(hour=18, minute=0, tzinfo=BR_TZ)
])
async def noticias_diarias():
    if not config.NEWS_ATIVAS or not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    noticias = news.noticias()
    if not noticias:
        return

    await canal.send(embed=embed_jornal(noticias))

@tasks.loop(time=time(hour=18, minute=0, tzinfo=BR_TZ))
async def resumo_semanal():
    hoje = datetime.now(BR_TZ)
    if hoje.weekday() != 4 or not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)

    embed = discord.Embed(
        title="📅 Resumo Semanal do Mercado",
        description="Encerramento da semana financeira",
        color=0x9B59B6
    )

    embed.add_field(
        name="📊 Visão Geral",
        value="• Semana marcada por volatilidade\n• Atenção a dados macroeconômicos",
        inline=False
    )

    embed.add_field(
        name="🧠 Leitura do Bot",
        value="• Avaliar posições\n• Planejar próxima semana com cautela",
        inline=False
    )

    await canal.send(embed=embed)

# ─────────────────────────────
# BEFORE LOOP (OBRIGATÓRIO)
# ─────────────────────────────

@analise_diaria.before_loop
async def before_analise():
    await bot.wait_until_ready()

@noticias_diarias.before_loop
async def before_noticias():
    await bot.wait_until_ready()

@resumo_semanal.before_loop
async def before_resumo():
    await bot.wait_until_ready()

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
