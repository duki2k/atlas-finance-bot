import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
import requests
from datetime import datetime
import pytz
import asyncio

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
# ESTADO DO BOT
# ─────────────────────────────

ultimo_relatorio = None
ultimo_jornal_manha = None
ultimo_jornal_tarde = None

ULTIMOS_PRECOS = {}
FALHAS_ATIVOS = {}

# ─────────────────────────────
# MAPA DE ATIVOS (NOME + TIPO)
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

    # Criptos
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

def dolar_para_real():
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        ).json()
        return float(r["rates"]["BRL"])
    except:
        return 5.0


async def log_bot(titulo, mensagem, tipo="INFO"):
    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return

    cores = {
        "INFO": 0x3498DB,
        "SUCESSO": 0x2ECC71,
        "AVISO": 0xF1C40F,
        "ERRO": 0xE74C3C
    }

    embed = discord.Embed(
        title=f"📋 {titulo}",
        description=mensagem,
        color=cores.get(tipo, 0x95A5A6)
    )

    embed.set_footer(
        text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
    )

    await canal.send(embed=embed)


async def buscar_preco_com_fallback(ativo):
    # tentativa principal
    try:
        preco = market.preco_atual(ativo)
        if preco and preco > 0:
            return preco
    except:
        pass

    # retry simples
    await asyncio.sleep(1)
    try:
        preco = market.preco_atual(ativo)
        if preco and preco > 0:
            return preco
    except:
        pass

    # fallback de ticker (ações com hífen)
    if not ativo.endswith("-USD") and "-" in ativo:
        alt = ativo.replace("-", ".")
        try:
            preco = market.preco_atual(alt)
            if preco and preco > 0:
                return preco
        except:
            pass

    return None


def calcular_variacao(ativo, preco):
    anterior = ULTIMOS_PRECOS.get(ativo)
    ULTIMOS_PRECOS[ativo] = preco

    if not anterior:
        return 0.0, "⏺️ 0.00%"

    v = ((preco - anterior) / anterior) * 100
    if v > 0:
        return v, f"🔼 +{v:.2f}%"
    elif v < 0:
        return v, f"🔽 {v:.2f}%"
    return 0.0, "⏺️ 0.00%"


def cor_dinamica(valores):
    pos = sum(1 for v in valores if v > 0)
    neg = sum(1 for v in valores if v < 0)
    if pos > neg:
        return 0x2ECC71
    if neg > pos:
        return 0xE74C3C
    return 0xF1C40F

# ─────────────────────────────
# EMBEDS
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
    variacoes = []
    acoes, criptos = [], []

    for ativo, preco in dados.items():
        nome, _ = ATIVOS_INFO.get(ativo, (ativo, ""))
        vnum, vtxt = calcular_variacao(ativo, preco)
        variacoes.append(vnum)

        linha = (
            f"**{nome}** (`{ativo}`)\n"
            f"💲 ${preco:,.2f} | 🇧🇷 R$ {preco*cotacao:,.2f}\n"
            f"📉 {vtxt}"
        )

        if ativo.endswith("-USD"):
            criptos.append(linha)
        else:
            acoes.append(linha)

    embed = discord.Embed(
        title="📊 Relatório Diário de Ativos",
        description="Panorama consolidado do mercado",
        color=cor_dinamica(variacoes)
    )

    if acoes:
        embed.add_field(name="📈 Ações", value="\n\n".join(acoes), inline=False)
    if criptos:
        embed.add_field(name="🪙 Criptomoedas", value="\n\n".join(criptos), inline=False)

    embed.set_footer(text=f"Atualizado em {agora}")
    return embed


def embed_jornal(noticias):
    embed = discord.Embed(
        title="🗞️ Jornal do Mercado Global",
        description="Resumo das principais notícias financeiras",
        color=0x3498DB
    )

    embed.add_field(
        name="🌍 Destaques",
        value="\n\n".join(f"• {n}" for n in noticias[:6]),
        inline=False
    )

    embed.set_footer(text="Atlas Finance Bot")
    return embed

# ─────────────────────────────
# ENVIO DE CONTEÚDO
# ─────────────────────────────

async def enviar_relatorio():
    dados = {}
    cotacao = dolar_para_real()

    for ativo in config.ATIVOS:
        preco = await buscar_preco_com_fallback(ativo)

        if preco is None:
            FALHAS_ATIVOS[ativo] = FALHAS_ATIVOS.get(ativo, 0) + 1
            if FALHAS_ATIVOS[ativo] >= 3:
                await log_bot(
                    "Ativo instável",
                    f"`{ativo}` falhou {FALHAS_ATIVOS[ativo]} vezes seguidas.",
                    "ERRO"
                )
            continue
        else:
            FALHAS_ATIVOS.pop(ativo, None)

        dados[ativo] = preco

    if not dados:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    if canal:
        await canal.send(embed=embed_relatorio(dados, cotacao))


async def enviar_jornal():
    noticias = news.noticias()
    if not noticias:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    if canal:
        await canal.send(embed=embed_jornal(noticias))

# ─────────────────────────────
# EVENTO READY
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()

# ─────────────────────────────
# COMANDO ADMIN (ÚNICO NECESSÁRIO)
# ─────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await ctx.send("🧪 Enviando publicações...")
    await enviar_relatorio()
    await enviar_jornal()
    await ctx.send("✅ Publicações enviadas")

# ─────────────────────────────
# SCHEDULER AUTOMÁTICO
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_relatorio, ultimo_jornal_manha, ultimo_jornal_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_relatorio != agora.date():
        await enviar_relatorio()
        await enviar_jornal()
        ultimo_relatorio = agora.date()
        ultimo_jornal_manha = agora.date()

    if hora == "18:00" and ultimo_jornal_tarde != agora.date():
        await enviar_jornal()
        ultimo_jornal_tarde = agora.date()

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
