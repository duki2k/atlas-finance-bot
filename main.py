import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
import requests
from datetime import datetime
import pytz

# ─────────────────────────────
# CONFIGURAÇÕES
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
# CONTROLE DE DISPARO
# ─────────────────────────────

ultimo_envio_analise = None
ultimo_envio_jornal_manha = None
ultimo_envio_jornal_tarde = None

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

def sentimento_mercado(noticias):
    texto = " ".join(noticias).lower()
    pos = ["alta", "sobe", "ganho", "avanço", "recuperação"]
    neg = ["queda", "cai", "crise", "tensão", "volatilidade"]

    score = sum(p in texto for p in pos) - sum(n in texto for n in neg)

    if score >= 2:
        return "🟢 Positivo"
    elif score <= -2:
        return "🔴 Defensivo"
    return "🟡 Neutro"

def embed_relatorio(dados, cotacao):
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="📊 Relatório Diário de Ativos",
        description="Visão consolidada do mercado",
        color=0x1ABC9C
    )

    acoes = []
    criptos = []

    for ativo, preco in dados.items():
        nome, _ = ATIVOS_INFO.get(ativo, (ativo, ""))
        linha = f"**{nome}** (`{ativo}`)\n💲 ${preco:,.2f} | 🇧🇷 R$ {preco*cotacao:,.2f}"

        if ativo.endswith("-USD"):
            criptos.append(linha)
        else:
            acoes.append(linha)

    if acoes:
        embed.add_field(name="📈 Ações", value="\n\n".join(acoes), inline=False)
    if criptos:
        embed.add_field(name="🪙 Criptomoedas", value="\n\n".join(criptos), inline=False)

    embed.set_footer(text=f"Atlas Community ® 2026 • Atualizado em {agora}")
    return embed

def embed_jornal(noticias):
    embed = discord.Embed(
        title="🗞️ Jornal do Mercado Global",
        color=0xF39C12
    )

    embed.add_field(
        name="🌍 Destaques",
        value="\n\n".join(f"• {n}" for n in noticias[:6]),
        inline=False
    )

    embed.add_field(
        name="📊 Sentimento",
        value=sentimento_mercado(noticias),
        inline=False
    )

    return embed

# ─────────────────────────────
# EVENTO READY
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()

# ─────────────────────────────
# SCHEDULER CONFIÁVEL (1 MINUTO)
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_envio_analise
    global ultimo_envio_jornal_manha
    global ultimo_envio_jornal_tarde

    agora = datetime.now(BR_TZ)
    hora_min = agora.strftime("%H:%M")

    # ───── ANÁLISE 06:00 ─────
    if hora_min == "06:00" and ultimo_envio_analise != agora.date():
        dados = {}
        cotacao = dolar_para_real()

        for ativo in config.ATIVOS:
            try:
                dados[ativo] = market.preco_atual(ativo)
            except:
                pass

        if dados and config.CANAL_ANALISE:
            canal = bot.get_channel(config.CANAL_ANALISE)
            await canal.send(embed=embed_relatorio(dados, cotacao))
            ultimo_envio_analise = agora.date()

    # ───── JORNAL 06:00 ─────
    if hora_min == "06:00" and ultimo_envio_jornal_manha != agora.date():
        noticias = news.noticias()
        if noticias and config.CANAL_NOTICIAS:
            canal = bot.get_channel(config.CANAL_NOTICIAS)
            await canal.send(embed=embed_jornal(noticias))
            ultimo_envio_jornal_manha = agora.date()

    # ───── JORNAL 18:00 ─────
    if hora_min == "18:00" and ultimo_envio_jornal_tarde != agora.date():
        noticias = news.noticias()
        if noticias and config.CANAL_NOTICIAS:
            canal = bot.get_channel(config.CANAL_NOTICIAS)
            await canal.send(embed=embed_jornal(noticias))
            ultimo_envio_jornal_tarde = agora.date()

embed.set_footer(text=f"Atlas Community ® 2026 • Atualizado em {agora}")
    return embed

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
