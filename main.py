import os
import discord
from discord.ext import commands, tasks
import config
import market
import news

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

# 🔴 DESATIVA O HELP PADRÃO DO DISCORD
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# 🚨 LISTA DE ALERTAS
ALERTAS = []

@bot.event
async def on_ready():
    print("🤖 Bot hobby ligado")
    analise_automatica.start()
    noticias_diarias.start()
    verificar_alertas.start()

# ───── COMANDOS USUÁRIO ─────

@bot.command()
async def preco(ctx, ativo):
    try:
        p = market.preco_atual(ativo)
        embed = discord.Embed(
            title="💰 Preço do ativo",
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

        embed = discord.Embed(
            title=f"📊 Análise — {ativo}",
            color=0x2ecc71
        )
        embed.add_field(name="Preço", value=f"{p:.2f}", inline=True)
        embed.add_field(name="RSI", value=f"{r:.1f}", inline=True)
        embed.add_field(name="Tendência", value=t, inline=False)

        await ctx.send(embed=embed)
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

@bot.command()
async def alerta(ctx, ativo, valor: float):
    ALERTAS.append({
        "ativo": ativo,
        "valor": valor,
        "canal": ctx.channel.id
    })
    await ctx.send(f"🚨 Alerta criado para **{ativo}** em `{valor}`")

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance Bot — Comandos",
        description="Acompanhe o mercado financeiro em tempo real 📈",
        color=0x00ff99
    )

    embed.add_field(
        name="👥 Comandos para todos",
        value=(
            "`!preco ATIVO`\n"
            "`!analise ATIVO`\n"
            "`!tendencia ATIVO`\n"
            "`!ativos`\n"
            "`!alerta ATIVO VALOR`"
        ),
        inline=False
    )

    embed.add_field(
        name="👑 Comandos admin",
        value=(
            "`!setcanal`\n"
            "`!add ATIVO`\n"
            "`!remove ATIVO`\n"
            "`!intervalo
