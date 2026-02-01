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
import whatsapp

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

ultimo_manha = None
ultimo_tarde = None

# ─────────────────────────────
# MAPA DE NOMES
# ─────────────────────────────

ATIVOS_INFO = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL": "Google",
    "TSLA": "Tesla",
    "NVDA": "Nvidia",
    "META": "Meta",
    "BRK-B": "Berkshire Hathaway",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "ADA-USD": "Cardano",
    "XRP-USD": "XRP",
    "BNB-USD": "Binance Coin"
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


def sentimento_emoji(positivos, negativos):
    if positivos > negativos:
        return "😄 Mercado positivo"
    if negativos > positivos:
        return "😨 Mercado defensivo"
    return "😐 Mercado neutro"


async def log_bot(titulo, mensagem):
    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return

    embed = discord.Embed(
        title=f"📋 {titulo}",
        description=mensagem,
        color=0x3498DB
    )
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

# ─────────────────────────────
# EMBEDS
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    acoes, criptos = [], []
    altas, quedas = [], []

    for ativo, (preco, variacao) in dados.items():
        nome = ATIVOS_INFO.get(ativo, ativo)

        emoji = "🔼" if variacao > 0 else "🔽" if variacao < 0 else "⏺️"
        texto_var = f"{emoji} {variacao:.2f}%"

        linha = (
            f"**{nome}** (`{ativo}`)\n"
            f"💲 ${preco:,.2f} | 🇧🇷 R$ {preco * cotacao:,.2f}\n"
            f"📉 {texto_var}"
        )

        if variacao > 0:
            altas.append((nome, variacao))
        elif variacao < 0:
            quedas.append((nome, variacao))

        if ativo.endswith("-USD"):
            criptos.append(linha)
        else:
            acoes.append(linha)

    altas = sorted(altas, key=lambda x: x[1], reverse=True)[:3]
    quedas = sorted(quedas, key=lambda x: x[1])[:3]

    sentimento = sentimento_emoji(len(altas), len(quedas))
    cor = 0x2ECC71 if len(altas) > len(quedas) else 0xE74C3C if len(quedas) > len(altas) else 0xF1C40F

    embed = discord.Embed(
        title="📊 Relatório Diário de Ativos",
        description=sentimento,
        color=cor
    )

    if altas:
        embed.add_field(
            name="🔝 Top 3 Altas",
            value="\n".join(f"{n} (+{v:.2f}%)" for n, v in altas),
            inline=False
        )

    if quedas:
        embed.add_field(
            name="🔻 Top 3 Quedas",
            value="\n".join(f"{n} ({v:.2f}%)" for n, v in quedas),
            inline=False
        )

    if acoes:
        embed.add_field(name="📈 Ações", value="\n\n".join(acoes), inline=False)

    if criptos:
        embed.add_field(name="🪙 Criptomoedas", value="\n\n".join(criptos), inline=False)

    embed.set_footer(text="Dados reais do mercado • Atlas Finance Bot")
    return embed


def embed_jornal(noticias):
    embed = discord.Embed(
        title="🗞️🌍 Jornal do Mercado",
        description="Resumo do que está movimentando o mercado hoje 🚀",
        color=0x00BFFF
    )

    embed.add_field(
        name="🔥 Manchetes",
        value="\n\n".join(f"📰 {n}" for n in noticias[:6]),
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
        try:
            preco, variacao = market.dados_ativo(ativo)
            if preco is None or variacao is None:
                continue
            dados[ativo] = (preco, variacao)
        except Exception as e:
            await log_bot("Erro ativo", f"{ativo}\n{e}")

    if not dados:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    if canal:
        await canal.send(embed=embed_relatorio(dados, cotacao))

    texto = gerar_recomendacao_whatsapp(dados)
    whatsapp.enviar_whatsapp(texto)


async def enviar_jornal():
    noticias = news.noticias()
    if not noticias:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    if canal:
        await canal.send(embed=embed_jornal(noticias))

# ─────────────────────────────
# TEXTO WHATSAPP
# ─────────────────────────────

def gerar_recomendacao_whatsapp(dados):
    altas, quedas = [], []

    for _, (preco, variacao) in dados.items():
        if variacao > 0:
            altas.append(variacao)
        elif variacao < 0:
            quedas.append(variacao)

    sentimento = sentimento_emoji(len(altas), len(quedas))

    texto = f"📊 *Resumo do Mercado*\n{sentimento}\n\n"

    texto += "🧠 *Postura do dia*\n"
    if len(altas) > len(quedas):
        texto += "Mercado mais favorável, mas com cautela.\n"
    elif len(quedas) > len(altas):
        texto += "Cenário defensivo. Preserve capital.\n"
    else:
        texto += "Mercado lateral. Seletividade é chave.\n"

    texto += "\n— Atlas Finance"
    return texto

# ─────────────────────────────
# EVENTO READY
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()

# ─────────────────────────────
# COMANDOS ADMIN
# ─────────────────────────────

@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    await ctx.send(
        "**Comandos disponíveis:**\n"
        "!testarpublicacoes\n"
        "!reiniciar"
    )


@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await enviar_relatorio()
    await enviar_jornal()
    await ctx.send("✅ Publicações enviadas")


@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()

# ─────────────────────────────
# SCHEDULER
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_manha, ultimo_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_manha != agora.date():
        await enviar_relatorio()
        await enviar_jornal()
        ultimo_manha = agora.date()

    if hora == "18:00" and ultimo_tarde != agora.date():
        await enviar_jornal()
        ultimo_tarde = agora.date()

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
