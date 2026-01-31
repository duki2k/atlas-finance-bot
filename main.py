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
# MAPA DE ATIVOS (NOME + TIPO)
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
    "JPM": ("JPMorgan Chase & Co.", "Ação EUA"),
    "V": ("Visa Inc.", "Ação EUA"),
    "MA": ("Mastercard Incorporated", "Ação EUA"),
    "UNH": ("UnitedHealth Group", "Ação EUA"),
    "DIS": ("Walt Disney Company", "Ação EUA"),
    "PG": ("Procter & Gamble", "Ação EUA"),
    "KO": ("Coca-Cola Company", "Ação EUA"),
    "PEP": ("PepsiCo Inc.", "Ação EUA"),
    "INTC": ("Intel Corporation", "Ação EUA"),
    "CSCO": ("Cisco Systems", "Ação EUA"),
    "XOM": ("Exxon Mobil", "Ação EUA"),
    "CVX": ("Chevron Corporation", "Ação EUA"),
    "BAC": ("Bank of America", "Ação EUA"),
    "WMT": ("Walmart Inc.", "Ação EUA"),
    "HD": ("Home Depot Inc.", "Ação EUA"),
    "VZ": ("Verizon Communications", "Ação EUA"),
    "ADBE": ("Adobe Inc.", "Ação EUA"),
    "BTC-USD": ("Bitcoin", "Criptomoeda"),
    "ETH-USD": ("Ethereum", "Criptomoeda"),
    "USDT-USD": ("Tether", "Criptomoeda"),
    "BNB-USD": ("Binance Coin", "Criptomoeda"),
    "XRP-USD": ("XRP", "Criptomoeda"),
    "ADA-USD": ("Cardano", "Criptomoeda"),
}

# ─────────────────────────────
# UTILIDADES
# ─────────────────────────────

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
    positivas = ["alta", "sobe", "ganho", "avanço", "recuperação", "otimismo"]
    negativas = ["queda", "cai", "crise", "tensão", "volatilidade", "inflação"]

    score = sum(p in texto for p in positivas) - sum(n in texto for n in negativas)

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

def admin_channel_only(ctx):
    if not config.CANAL_ADMIN:
        return False
    return ctx.channel.id == config.CANAL_ADMIN

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
        name="📊 Automático",
        value=(
            "• Relatório diário de ativos (06h)\n"
            "• Jornal do mercado (06h e 18h)\n"
            "• Resumo semanal (sexta 18h)"
        ),
        inline=False
    )

    embed.add_field(
        name="🧪 Testes / Manutenção",
        value=(
            "`!testenoticias`\n"
            "`!manutencao`\n"
            "`!statusbot`"
        ),
        inline=False
    )

    embed.add_field(
        name="🔒 Configuração",
        value=(
            "`!setcanal`\n"
            "`!setcanalnoticias`\n"
            "`!setcanaladmin`"
        ),
        inline=False
    )

    embed.set_footer(text="Acesso restrito • Administradores")
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
    await ctx.send("🔒 Canal administrativo definido")

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

@bot.command()
@commands.has_permissions(administrator=True)
async def statusbot(ctx):
    if not admin_channel_only(ctx):
        return

    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(title="📡 Status do Bot", color=0x2ECC71)
    embed.add_field(name="Bot", value=str(bot.user), inline=False)
    embed.add_field(name="Horário atual", value=agora, inline=True)
    embed.add_field(name="Notícias", value="Ativas" if config.NEWS_ATIVAS else "Desativadas", inline=True)

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

    await canal.send("📈 **Relatório diário de ativos — 06:00**")

    for ativo in config.ATIVOS:
        try:
            usd = market.preco_atual(ativo)
            brl = usd * cotacao
            embed = embed_ativo(ativo, usd, brl)
            await canal.send(embed=embed)
        except:
            pass

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

@tasks.loop(time=time(hour=18, minute=0, tzinfo=BR_TZ))
async def resumo_semanal():
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
            "• Avaliar posições abertas\n"
            "• Reduzir exposição excessiva\n"
            "• Planejar próxima semana com cautela"
        ),
        inline=False
    )

    embed.set_footer(text="Resumo Semanal")
    await canal.send(embed=embed)

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
