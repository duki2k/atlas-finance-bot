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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ─────────────────────────────
# ESTADO GLOBAL
# ─────────────────────────────

ultimo_analise = None
ultimo_jornal_manha = None
ultimo_jornal_tarde = None

ULTIMOS_PRECOS = {}
FALHAS_ATIVOS = {}

# ─────────────────────────────
# MAPA DE ATIVOS
# ─────────────────────────────

ATIVOS_INFO = {
    # Ações
    "AAPL": ("Apple Inc.", "Ação EUA"),
    "MSFT": ("Microsoft Corporation", "Ação EUA"),
    "AMZN": ("Amazon.com Inc.", "Ação EUA"),
    "GOOGL": ("Alphabet Inc.", "Ação EUA"),
    "TSLA": ("Tesla Inc.", "Ação EUA"),
    "NVDA": ("NVIDIA Corporation", "Ação EUA"),
    "META": ("Meta Platforms Inc.", "Ação EUA"),
    "BRK-B": ("Berkshire Hathaway Inc.", "Ação EUA"),

    # Criptomoedas
    "BTC-USD": ("Bitcoin", "Criptomoeda"),
    "ETH-USD": ("Ethereum", "Criptomoeda"),
    "SOL-USD": ("Solana", "Criptomoeda"),
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


def calcular_variacao(ativo, preco_atual):
    anterior = ULTIMOS_PRECOS.get(ativo)
    ULTIMOS_PRECOS[ativo] = preco_atual

    if not anterior or anterior == 0:
        return 0.0, "⏺️ 0.00%"

    variacao = ((preco_atual - anterior) / anterior) * 100

    if variacao > 0:
        return variacao, f"🔼 +{variacao:.2f}%"
    elif variacao < 0:
        return variacao, f"🔽 {variacao:.2f}%"
    return 0.0, "⏺️ 0.00%"


def cor_dinamica(variacoes):
    altas = sum(1 for v in variacoes if v > 0)
    baixas = sum(1 for v in variacoes if v < 0)

    if altas > baixas:
        return 0x2ECC71
    elif baixas > altas:
        return 0xE74C3C
    return 0xF1C40F


async def log_bot(titulo, mensagem, tipo="INFO"):
    if not config.CANAL_LOGS:
        return

    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return

    cores = {
        "INFO": 0x3498DB,
        "AVISO": 0xF1C40F,
        "ERRO": 0xE74C3C,
        "SUCESSO": 0x2ECC71
    }

    embed = discord.Embed(
        title=f"📋 {titulo}",
        description=mensagem,
        color=cores.get(tipo, 0x95A5A6)
    )

    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

# ─────────────────────────────
# FALLBACK DE PREÇO (AÇÕES + CRIPTOS)
# ─────────────────────────────

async def buscar_preco_com_fallback(ativo):
    # 1️⃣ tentativa padrão
    try:
        preco = market.preco_atual(ativo)
        if preco and preco > 0:
            return preco
    except:
        pass

    # 2️⃣ retry simples
    await asyncio.sleep(1)
    try:
        preco = market.preco_atual(ativo)
        if preco and preco > 0:
            return preco
    except:
        pass

    # 3️⃣ fallback para ações com ticker alternativo
    if not ativo.endswith("-USD") and "-" in ativo:
        alternativo = ativo.replace("-", ".")
        await asyncio.sleep(1)
        try:
            preco = market.preco_atual(alternativo)
            if preco and preco > 0:
                return preco
        except:
            pass

    return None

# ─────────────────────────────
# EMBEDS
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
    variacoes = []
    acoes, criptos = [], []

    for ativo, preco in dados.items():
        nome, _ = ATIVOS_INFO.get(ativo, (ativo, ""))
        v_num, v_txt = calcular_variacao(ativo, preco)
        variacoes.append(v_num)

        linha = (
            f"**{nome}** (`{ativo}`)\n"
            f"💲 ${preco:,.2f} | 🇧🇷 R$ {preco*cotacao:,.2f}\n"
            f"📉 Variação: {v_txt}"
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

    embed.set_footer(text="Atlas Finance Bot • Atualização automática")
    return embed

# ─────────────────────────────
# ENVIO DE RELATÓRIO (COM VALIDAÇÃO)
# ─────────────────────────────

async def enviar_relatorio_agora():
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
                    tipo="ERRO"
                )
            continue
        else:
            FALHAS_ATIVOS.pop(ativo, None)

        dados[ativo] = preco

    if not dados:
        await log_bot(
            "Relatório diário",
            "Nenhum ativo válido encontrado.",
            tipo="ERRO"
        )
        return

    if config.CANAL_ANALISE:
        canal = bot.get_channel(config.CANAL_ANALISE)
        if canal:
            await canal.send(embed=embed_relatorio(dados, cotacao))

# ─────────────────────────────
# ENVIO DE JORNAL
# ─────────────────────────────

async def enviar_jornal_agora():
    noticias = news.noticias()
    if not noticias:
        await log_bot("Jornal", "Nenhuma notícia retornada.", "AVISO")
        return

    if config.CANAL_NOTICIAS:
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
# COMANDO ADMIN (TESTE MANUAL)
# ─────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await ctx.send("🧪 Enviando publicações...")
    await enviar_relatorio_agora()
    await enviar_jornal_agora()
    await ctx.send("✅ Publicações enviadas")

# ─────────────────────────────
# SCHEDULER CONFIÁVEL
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_analise, ultimo_jornal_manha, ultimo_jornal_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_analise != agora.date():
        await enviar_relatorio_agora()
        ultimo_analise = agora.date()

    if hora == "06:00" and ultimo_jornal_manha != agora.date():
        await enviar_jornal_agora()
        ultimo_jornal_manha = agora.date()

    if hora == "18:00" and ultimo_jornal_tarde != agora.date():
        await enviar_jornal_agora()
        ultimo_jornal_tarde = agora.date()

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
