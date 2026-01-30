import os
import discord
from discord.ext import commands, tasks
import yfinance as yf
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

CANAL_ANALISE = None
ATIVOS = ["PETR4.SA", "VALE3.SA", "AAPL", "BTC-USD"]

@bot.event
async def on_ready():
    print("Bot ligado")
    analise_automatica.start()

@bot.command()
async def preco(ctx, ativo):
    try:
        ticker = yf.Ticker(ativo)
        preco = ticker.history(period="1d")["Close"].iloc[-1]
        await ctx.send(f"💰 {ativo}: {preco:.2f}")
    except:
        await ctx.send("Ativo inválido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanal(ctx):
    global CANAL_ANALISE
    CANAL_ANALISE = ctx.channel.id
    await ctx.send("Canal definido")

@tasks.loop(hours=1)
async def analise_automatica():
    if not CANAL_ANALISE:
        return
    canal = bot.get_channel(CANAL_ANALISE)
    for ativo in ATIVOS:
        try:
            ticker = yf.Ticker(ativo)
            preco = ticker.history(period="1d")["Close"].iloc[-1]
            await canal.send(f"📈 {ativo} → {preco:.2f}")
        except:
            pass

bot.run(TOKEN)
