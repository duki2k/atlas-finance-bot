import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
import requests
from datetime import time, datetime
import pytz

# ───── CONFIGURAÇÕES ─────

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ───── MAPA DE ATIVOS ─────

ATIVOS_INFO = {
    "AAPL": ("Apple Inc.", "Ação EUA"),
    "MSFT": ("Microsoft Corporation", "Ação EUA"),
    "AMZN": ("Amazon.com Inc.", "Ação EUA"),
    "GOOGL": ("Alphabet Inc.", "Ação EUA"),
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

# ───── UTILIDADES ─────

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
    pos = ["alta","sobe","ganho","avanço","recuperação"]
    neg = ["queda","cai","crise","tensão","volatilidade"]
    score = sum(p in texto for p in pos) - sum(n in texto for n in neg)

    if score >= 2:
        return "🟢 Sentimento positivo — mercado construtivo"
    elif score <= -2:
        return "🔴 Sentimento defensivo — cautela recomendada"
    return "🟡 Sentimento neutro — mercado indefinido"

def embed_ativo(ativo, usd, brl):
    nome, tipo = ATIVOS_INFO.get(ativo, (ativo, "Ativo Financeiro"))
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y às %H:%M")

    embed = discord.Embed(
        title=f"📊 {nome}",
        description=f"**Ticker:** `{ativo}`\n**Tipo:** {tipo}",
        color=0x2ECC71
    )

    embed.add_field(name="💲 USD", value=f"${usd:,.2f}", inline=True)
    embed.add_field(name="🇧🇷 BRL", value=f"R$ {brl:,.2f}", inline=True)
    embed.set_footer(text=f"Atualizado em {agora}")

    return embed

# ───── EVENTO ─────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    analise_diaria.start()
    noticias_diarias.start()

# ───── COMANDOS (ADMIN ONLY) ─────

@bot.command()
@commands.has_permissions(administrator=True)
async def help(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance Bot — Painel Admin",
        description="Bot automático de mercado financeiro",
        color=0x3498DB
    )

    embed.add_field(
        name="📊 Automático",
        value="• Relatório diário de ativos (06h)\n• Jornal do mercado (06h e 18h)",
        inline=False
    )

    embed.add_field(
        name="🧪 Testes",
        value="`!testenoticias` — testar portal de notícias",
        inline=False
    )

    embed.add_field(
        name="⚙️ Configuração",
        value="`!setcanal`\n`!setcanalnoticias`",
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
async def testenoticias(ctx):
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

# ───── TASK: ANÁLISE DIÁRIA ─────

@tasks.loop(time=time(hour=6, minute=0, tzinfo=BR_TZ))
async def analise_diaria():
    if not config.CANAL_ANALISE:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    cotacao = dolar_para_real()

    await canal.send("📈 **Relatório diário de ativos — 06:00**")

    for ativo in config.ATIVOS:
        try:
            usd = market.preco_atual(ativo)
            brl = usd * cotacao
            embed = embed_ativo(ativo, usd, brl)
            await canal.send(embed=embed)
        except:
            pass

# ───── TASK: NOTÍCIAS ─────

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

    embed.set_footer(text="Conteúdo educacional • Atlas Community")
    await canal.send(embed=embed)

# ───── START ─────

bot.run(TOKEN)
