import os
import discord
from discord.ext import commands, tasks
import config
import market
import news

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print("🤖 Bot hobby ligado")
    analise_automatica.start()
    noticias_diarias.start()

# ───── COMANDOS USUÁRIO ─────

@bot.command()
async def preco(ctx, ativo):
    try:
        p = market.preco_atual(ativo)
        await ctx.send(f"💰 **{ativo}** → {p:.2f}")
    except:
        await ctx.send("❌ Ativo inválido")

@bot.command()
async def preco(ctx, ativo):
    try:
        p = market.preco_atual(ativo)

        embed = discord.Embed(
            title=f"💰 Preço do ativo",
            description=f"**{ativo}**",
            color=0x3498db
        )
        embed.add_field(name="Preço atual", value=f"{p:.2f}", inline=False)

        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Ativo inválido")


@bot.command()
async def analise(ctx, ativo):
    try:
        p = market.preco_atual(ativo)
        r = market.rsi(ativo)
        t = market.tendencia(ativo)
        await ctx.send(
            f"📊 **{ativo}**\n"
            f"Preço: {p:.2f}\n"
            f"RSI: {r:.1f}\n"
            f"Tendência: {t}"
        )
    except:
        await ctx.send("❌ Não consegui analisar esse ativo")

@bot.command()
async def tendencia(ctx, ativo):
    try:
        t = market.tendencia(ativo)
        await ctx.send(f"📈 **{ativo}** → {t}")
    except:
        await ctx.send("❌ Ativo inválido")

@bot.command()
async def ativos(ctx):
    await ctx.send("📌 Ativos monitorados:\n" + ", ".join(config.ATIVOS))

# ───── COMANDOS ADMIN ─────

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanal(ctx):
    config.CANAL_ANALISE = ctx.channel.id
    await ctx.send("✅ Canal de análises definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, ativo):
    config.ATIVOS.append(ativo)
    await ctx.send(f"✅ {ativo} adicionado")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, ativo):
    config.ATIVOS.remove(ativo)
    await ctx.send(f"🗑️ {ativo} removido")

@bot.command()
@commands.has_permissions(administrator=True)
async def intervalo(ctx, minutos: int):
    config.INTERVALO_MINUTOS = minutos
    analise_automatica.change_interval(minutes=minutos)
    await ctx.send(f"⏱️ Intervalo alterado para {minutos} minutos")

@bot.command()
@commands.has_permissions(administrator=True)
async def news_on(ctx):
    config.NEWS_ATIVAS = True
    await ctx.send("📰 Notícias ativadas")

@bot.command()
@commands.has_permissions(administrator=True)
async def news_off(ctx):
    config.NEWS_ATIVAS = False
    await ctx.send("📰 Notícias desativadas")

# ───── TAREFAS AUTOMÁTICAS ─────

@tasks.loop(minutes=config.INTERVALO_MINUTOS)
async def analise_automatica():
    if not config.CANAL_ANALISE:
        return
    canal = bot.get_channel(config.CANAL_ANALISE)
    for ativo in config.ATIVOS:
        try:
            p = market.preco_atual(ativo)
            await canal.send(f"📈 {ativo} → {p:.2f}")
        except:
            pass

@tasks.loop(hours=24)
async def noticias_diarias():
    if not config.NEWS_ATIVAS or not config.CANAL_ANALISE:
        return
    canal = bot.get_channel(config.CANAL_ANALISE)
    for n in news.noticias():
        await canal.send(n)

bot.run(TOKEN)
