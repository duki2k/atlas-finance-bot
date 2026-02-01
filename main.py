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
# MAPA DE ATIVOS
# ─────────────────────────────

ATIVOS_INFO = {
    "AAPL": ("Apple Inc.", "Ação EUA"),
    "MSFT": ("Microsoft Corporation", "Ação EUA"),
    "AMZN": ("Amazon.com Inc.", "Ação EUA"),
    "GOOGL": ("Alphabet Inc. (Google)", "Ação EUA"),
    "TSLA": ("Tesla Inc.", "Ação EUA"),
    "NVDA": ("NVIDIA Corporation", "Ação EUA"),
    "META": ("Meta Platforms Inc.", "Ação EUA"),
    "BRK-B": ("Berkshire Hathaway Inc.", "Ação EUA"),
    "BTC-USD": ("Bitcoin", "Criptomoeda"),
    "ETH-USD": ("Ethereum", "Criptomoeda"),
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
        return 5.0

def sentimento_mercado(noticias):
    texto = " ".join(noticias).lower()
    positivas = ["alta", "sobe", "ganho", "avanço", "recuperação"]
    negativas = ["queda", "cai", "crise", "volatilidade", "tensão"]

    score = sum(p in texto for p in positivas) - sum(n in texto for n in negativas)

    if score >= 2:
        return "🟢 Sentimento positivo"
    elif score <= -2:
        return "🔴 Sentimento defensivo"
    return "🟡 Sentimento neutro"

def embed_ativo(ativo, usd, brl):
    nome, tipo = ATIVOS_INFO.get(ativo, (ativo, "Ativo Financeiro"))
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title=f"📊 {nome}",
        description=f"**Ticker:** `{ativo}`\n**Tipo:** {tipo}",
        color=0x2ECC71
    )
    embed.add_field(name="💲 USD", value=f"${usd:,.2f}", inline=True)
    embed.add_field(name="🇧🇷 BRL", value=f"R$ {brl:,.2f}", inline=True)
    embed.set_footer(text=f"Atualizado em {agora}")
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
        value=(
            "`!setcanal`\n"
            "`!setcanalnoticias`\n"
            "`!setcanaladmin`"
        ),
        inline=False
    )

    embed.add_field(
        name="🧪 Testes",
        value=(
            "`!testenoticias`\n"
            "`!testarpublicacoes`\n"
            "`!statusbot`\n"
            "`!manutencao`"
        ),
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

    embed = discord.Embed(
        title="🧪 Teste de Notícias",
        description="\n".join(f"• {n}" for n in noticias[:5]),
        color=0xE67E22
    )
    await ctx.send(embed=embed)

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

@bot.command()
@commands.has_permissions(administrator=True)
async def manutencao(ctx):
    if not admin_channel_only(ctx):
        return

    try:
        market.preco_atual("BTC-USD")
        status_api = "OK"
    except:
        status_api = "FALHA"

    embed = discord.Embed(title="🛠️ Manutenção", color=0xE67E22)
    embed.add_field(name="API de preços", value=status_api, inline=False)
    embed.add_field(name="Canal Análises", value="OK" if config.CANAL_ANALISE else "❌", inline=True)
    embed.add_field(name="Canal Notícias", value="OK" if config.CANAL_NOTICIAS else "❌", inline=True)
    embed.add_field(name="Canal Admin", value="OK" if config.CANAL_ADMIN else "❌", inline=True)
    await ctx.send(embed=embed)

# ─────────────────────────────
# TASKS AUTOMÁTICAS
# ─────────────────────────────

@tasks.loop(time=time(hour=6, minute=0, tzinfo=BR_TZ))
async def analise_diaria():
    print("📊 Executando analise_diaria")

    if not config.CANAL_ANALISE:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    cotacao = dolar_para_real()

    await canal.send("📈 **Relatório diário de ativos — 06:00**")

    for ativo in config.ATIVOS:
        try:
            usd = market.preco_atual(ativo)
            brl = usd * cotacao
            await canal.send(embed=embed_ativo(ativo, usd, brl))
        except:
            pass

@tasks.loop(time=[
    time(hour=6, minute=0, tzinfo=BR_TZ),
    time(hour=18, minute=0, tzinfo=BR_TZ)
])
async def noticias_diarias():
    print("📰 Executando noticias_diarias")

    if not config.NEWS_ATIVAS or not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    noticias = news.noticias()
    if not noticias:
        return

    embed = discord.Embed(
        title="🗞️ Jornal do Mercado Global",
        description="\n".join(f"• {n}" for n in noticias[:5]),
        color=0xF1C40F
    )

    embed.add_field(
        name="📊 Sentimento do mercado",
        value=sentimento_mercado(noticias),
        inline=False
    )

    embed.set_footer(text="Atlas Community • Conteúdo educacional")
    await canal.send(embed=embed)

@tasks.loop(time=time(hour=18, minute=0, tzinfo=BR_TZ))
async def resumo_semanal():
    print("📅 Executando resumo_semanal")

    hoje = datetime.now(BR_TZ)
    if hoje.weekday() != 4:
        return

    if not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)

    embed = discord.Embed(
        title="📅 Resumo Semanal do Mercado",
        description="Encerramento da semana financeira",
        color=0x9B59B6
    )

    embed.add_field(
        name="📊 Visão Geral",
        value=(
            "• Semana marcada por volatilidade\n"
            "• Atenção a dados macroeconômicos\n"
            "• Fluxo seletivo para ativos de risco"
        ),
        inline=False
    )

    embed.add_field(
        name="🧠 Leitura do Bot",
        value=(
            "• Avaliar posições\n"
            "• Reduzir exposição excessiva\n"
            "• Planejar próxima semana"
        ),
        inline=False
    )

    await canal.send(embed=embed)

# ─────────────────────────────
# BEFORE LOOP (OBRIGATÓRIO)
# ─────────────────────────────

@analise_diaria.before_loop
async def before_analise():
    await bot.wait_until_ready()
    print("📊 analise_diaria pronta")

@noticias_diarias.before_loop
async def before_noticias():
    await bot.wait_until_ready()
    print("📰 noticias_diarias pronta")

@resumo_semanal.before_loop
async def before_resumo():
    await bot.wait_until_ready()
    print("📅 resumo_semanal pronta")

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
