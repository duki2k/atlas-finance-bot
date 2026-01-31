import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
from datetime import time
import pytz

# ───── TOKEN ─────

TOKEN = os.getenv("DISCORD_TOKEN")

# ───── INTENTS ─────

intents = discord.Intents.default()
intents.message_content = True

# ───── BOT ─────

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ───── ESTADO ─────

ALERTAS = []

# ───── EVENTO READY ─────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")

    if not analise_automatica.is_running():
        analise_automatica.start()

    if not noticias_diarias.is_running():
        noticias_diarias.start()

    if not verificar_alertas.is_running():
        verificar_alertas.start()

# ───── COMANDOS ─────

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance Bot",
        description="Comandos disponíveis",
        color=0x00ff99
    )
    embed.add_field(
        name="Usuários",
        value=(
            "!preco ATIVO\n"
            "!analise ATIVO\n"
            "!tendencia ATIVO\n"
            "!ativos\n"
            "!alerta ATIVO VALOR"
        ),
        inline=False
    )
    embed.add_field(
        name="Admin",
        value=(
            "!setcanal\n"
            "!setcanalnoticias\n"
            "!intervalo MIN\n"
            "!news on/off"
        ),
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
async def preco(ctx, ativo):
    try:
        p = market.preco_atual(ativo)
        await ctx.send(f"💰 **{ativo}** → {p:.2f}")
    except:
        await ctx.send("❌ Ativo não encontrado")

@bot.command()
async def analise(ctx, ativo):
    try:
        p = market.preco_atual(ativo)
        t = market.tendencia(ativo)
        await ctx.send(f"📊 **{ativo}**\nPreço: {p:.2f}\nTendência: {t}")
    except:
        await ctx.send("❌ Erro ao analisar")

@bot.command()
async def tendencia(ctx, ativo):
    try:
        t = market.tendencia(ativo)
        await ctx.send(f"📈 **{ativo}** → {t}")
    except:
        await ctx.send("❌ Ativo inválido")

@bot.command()
async def ativos(ctx):
    await ctx.send("📊 Ativos:\n" + ", ".join(config.ATIVOS))

@bot.command()
async def alerta(ctx, ativo, valor: float):
    ALERTAS.append({
        "ativo": ativo,
        "valor": valor,
        "canal": ctx.channel.id
    })
    await ctx.send(f"🚨 Alerta criado para {ativo} em {valor}")

# ───── COMANDOS ADMIN ─────

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
async def intervalo(ctx, minutos: int):
    config.INTERVALO_MINUTOS = minutos
    analise_automatica.change_interval(minutes=minutos)
    await ctx.send(f"⏱️ Intervalo alterado para {minutos} min")

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

@bot.command()
@commands.has_permissions(administrator=True)
async def jornalagora(ctx):
    if not config.NEWS_ATIVAS or not config.CANAL_NOTICIAS:
        await ctx.send("❌ Notícias desativadas ou canal não definido.")
        return

    noticias = news.noticias()
    if not noticias:
        await ctx.send("❌ Nenhuma notícia retornada.")
        return

    embed = discord.Embed(
        title="🗞️ Jornal do Mercado — TESTE MANUAL",
        description="\n".join(f"• {n}" for n in noticias[:5]),
        color=0xF39C12
    )
    embed.set_footer(text="Disparo manual para teste")

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    await canal.send(embed=embed)

    await ctx.send("✅ Jornal enviado manualmente.")


# ───── TASKS ─────

@tasks.loop(minutes=5)
async def verificar_alertas():
    for alerta in ALERTAS[:]:
        try:
            p = market.preco_atual(alerta["ativo"])
            if p >= alerta["valor"]:
                canal = bot.get_channel(alerta["canal"])
                await canal.send(f"🚨 {alerta['ativo']} atingiu {p:.2f}")
                ALERTAS.remove(alerta)
        except:
            pass

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

# ───── NOTÍCIAS FIXAS (TESTE 19:06) ─────

BR_TZ = pytz.timezone("America/Sao_Paulo")

@tasks.loop(time=time(hour=19, minute=6, tzinfo=BR_TZ))
async def noticias_diarias():
    if not config.NEWS_ATIVAS or not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    noticias = news.noticias()

    if not noticias:
        return

    embed = discord.Embed(
        title="🗞️ Jornal do Mercado — Abertura",
        description="\n".join(f"• {n}" for n in noticias[:5]),
        color=0xF39C12
    )
    embed.set_footer(text="Atualizado automaticamente • 19:06")
    await canal.send(embed=embed)

# ───── START ─────

bot.run(TOKEN)
