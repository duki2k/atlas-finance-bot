import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
import telegram
import requests
from datetime import datetime
import pytz
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

ultimo_manha = None
ultimo_tarde = None

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

def dolar_para_real():
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        ).json()
        return float(r["rates"]["BRL"])
    except:
        return 5.0

def sentimento_emoji(pos, neg):
    if pos > neg:
        return "😄 Mercado positivo"
    if neg > pos:
        return "😨 Mercado defensivo"
    return "😐 Mercado neutro"

async def log_bot(titulo, mensagem):
    canal = bot.get_channel(config.CANAL_LOGS)
    if canal:
        embed = discord.Embed(
            title=f"📋 {titulo}",
            description=mensagem,
            color=0x3498DB
        )
        embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
        await canal.send(embed=embed)

def embed_relatorio(dados, cotacao):
    acoes, criptos, altas, quedas = [], [], [], []

    for ativo, (preco, variacao) in dados.items():
        nome = ATIVOS_INFO.get(ativo, ativo)
        emoji = "🔼" if variacao > 0 else "🔽" if variacao < 0 else "⏺️"

        linha = (
            f"**{nome}** (`{ativo}`)\n"
            f"💲 ${preco:,.2f} | 🇧🇷 R$ {preco*cotacao:,.2f}\n"
            f"📉 {emoji} {variacao:.2f}%"
        )

        (altas if variacao > 0 else quedas if variacao < 0 else []).append((nome, variacao))

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
        embed.add_field(name="🔝 Top 3 Altas", value="\n".join(f"{n} (+{v:.2f}%)" for n,v in altas), inline=False)
    if quedas:
        embed.add_field(name="🔻 Top 3 Quedas", value="\n".join(f"{n} ({v:.2f}%)" for n,v in quedas), inline=False)
    if acoes:
        embed.add_field(name="📈 Ações", value="\n\n".join(acoes), inline=False)
    if criptos:
        embed.add_field(name="🪙 Criptomoedas", value="\n\n".join(criptos), inline=False)

    return embed

def gerar_texto_telegram(dados):
    altas, quedas = [], []

    for ativo, (_, v) in dados.items():
        nome = ATIVOS_INFO.get(ativo, ativo)
        if v > 0:
            altas.append((nome, v))
        elif v < 0:
            quedas.append((nome, v))

    altas = sorted(altas, key=lambda x: x[1], reverse=True)[:3]
    quedas = sorted(quedas, key=lambda x: x[1])[:3]

    texto = "📊 Resumo do Mercado\n"
    texto += sentimento_emoji(len(altas), len(quedas)) + "\n\n"

    if altas:
        texto += "🔝 Top Altas\n"
        texto += "\n".join(f"• {n}: +{v:.2f}%" for n,v in altas) + "\n\n"

    if quedas:
        texto += "🔻 Top Quedas\n"
        texto += "\n".join(f"• {n}: {v:.2f}%" for n,v in quedas) + "\n\n"

    texto += "— Atlas Finance"
    return texto

async def enviar_relatorio():
    dados = {}
    cotacao = dolar_para_real()

    for ativo in config.ATIVOS:
        try:
            preco, variacao = market.dados_ativo(ativo)
            if preco is not None and variacao is not None:
                dados[ativo] = (preco, variacao)
        except:
            continue

    if not dados:
        return

    canal = bot.get_channel(config.CANAL_ANALISE)
    if canal:
        await canal.send(embed=embed_relatorio(dados, cotacao))

    telegram.enviar_telegram(gerar_texto_telegram(dados))

async def enviar_jornal():
    noticias = news.noticias()
    if not noticias:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    if canal:
        embed = discord.Embed(
            title="🗞️ Jornal do Mercado",
            description="\n\n".join(f"📰 {n}" for n in noticias[:6]),
            color=0x00BFFF
        )
        await canal.send(embed=embed)

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()

@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    await ctx.send(
        "**Comandos (Admin):**\n"
        "`!testarpublicacoes`\n"
        "`!reiniciar`"
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
    await ctx.send("🔄 Reiniciando...")
    await asyncio.sleep(2)
    await bot.close()

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

bot.run(TOKEN)
