import os
import discord
from discord.ext import commands, tasks
import config
import market
import news
from datetime import time
import pytz

# ───── CONFIGURAÇÃO BÁSICA ─────

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

# desativa o help padrão do discord
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ───── ALERTAS ─────

ALERTAS = []

# ───── EVENTOS ─────

@bot.event
async def on_ready():
    print("🤖 Bot hobby ligado")

    if not analise_automatica.is_running():
        analise_automatica.start()

    if not noticias_diarias.is_running():
    noticias_diarias.start()

    if not verificar_alertas.is_running():
        verificar_alertas.start()


# ───── COMANDOS USUÁRIO ─────

@bot.command()
async def preco(ctx, ativo):
    try:
        preco = market.preco_atual(ativo)
        embed = discord.Embed(
            title="💰 Preço do ativo",
            description=f"**{ativo}**",
            color=0x3498db
        )
        embed.add_field(name="Preço atual", value=f"{preco:.2f}", inline=False)
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Não consegui encontrar esse ativo.")

@bot.command()
async def analise(ctx, ativo):
    try:
        preco = market.preco_atual(ativo)
        rsi = market.rsi(ativo)
        tendencia = market.tendencia(ativo)

        embed = discord.Embed(
            title=f"📊 Análise — {ativo}",
            color=0x2ecc71
        )
        embed.add_field(name="Preço", value=f"{preco:.2f}", inline=True)
        embed.add_field(name="RSI", value=f"{rsi:.1f}", inline=True)
        embed.add_field(name="Tendência", value=tendencia, inline=False)

        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Erro ao analisar esse ativo.")

@bot.command()
async def tendencia(ctx, ativo):
    try:
        tendencia = market.tendencia(ativo)
        await ctx.send(f"📈 **{ativo}** → {tendencia}")
    except:
        await ctx.send("❌ Ativo inválido.")

@bot.command()
async def ativos(ctx):
    criptos = []
    acoes = []

    for ativo in config.ATIVOS:
        if ativo.endswith("-USD"):
            criptos.append(ativo)
        else:
            acoes.append(ativo)

    embed = discord.Embed(
        title="📊 Ativos Monitorados",
        description="Lista de ativos acompanhados pelo bot",
        color=0x5865F2
    )

    if criptos:
        embed.add_field(
            name="🪙 Criptomoedas",
            value=" • ".join(criptos),
            inline=False
        )

    if acoes:
        embed.add_field(
            name="📈 Ações",
            value=" • ".join(acoes),
            inline=False
        )

    embed.set_footer(text=f"Total de ativos: {len(config.ATIVOS)}")

    await ctx.send(embed=embed)

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
        description="Acompanhe o mercado financeiro 📈",
        color=0x00ff99
    )

    embed.add_field(
        name="👥 Comandos para todos",
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
        name="👑 Comandos admin",
        value=(
            "!setcanal\n"
            "!add ATIVO\n"
            "!remove ATIVO\n"
            "!intervalo MIN\n"
            "!news on\n"
            "!news off"
        ),
        inline=False
    )

    embed.set_footer(text="Atlas Community ® 2026")

    await ctx.send(embed=embed)

# ───── COMANDOS ADMIN ─────

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanalnoticias(ctx):
    config.CANAL_NOTICIAS = ctx.channel.id
    await ctx.send("📰 Canal de notícias definido com sucesso.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanal(ctx):
    config.CANAL_ANALISE = ctx.channel.id
    await ctx.send("✅ Canal de análises definido.")

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, ativo):
    if ativo not in config.ATIVOS:
        config.ATIVOS.append(ativo)
        await ctx.send(f"✅ {ativo} adicionado.")
    else:
        await ctx.send("⚠️ Esse ativo já está na lista.")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, ativo):
    if ativo in config.ATIVOS:
        config.ATIVOS.remove(ativo)
        await ctx.send(f"🗑️ {ativo} removido.")
    else:
        await ctx.send("⚠️ Esse ativo não está na lista.")

@bot.command()
@commands.has_permissions(administrator=True)
async def intervalo(ctx, minutos: int):
    config.INTERVALO_MINUTOS = minutos
    analise_automatica.change_interval(minutes=minutos)
    await ctx.send(f"⏱️ Intervalo alterado para {minutos} minutos.")

@bot.command()
@commands.has_permissions(administrator=True)
async def news_on(ctx):
    config.NEWS_ATIVAS = True
    await ctx.send("📰 Notícias ativadas.")

@bot.command()
@commands.has_permissions(administrator=True)
async def news_off(ctx):
    config.NEWS_ATIVAS = False
    await ctx.send("📰 Notícias desativadas.")

# ───── TAREFAS AUTOMÁTICAS ─────

@tasks.loop(minutes=5)
async def verificar_alertas():
    for alerta in ALERTAS[:]:
        try:
            preco = market.preco_atual(alerta["ativo"])
            if preco >= alerta["valor"]:
                canal = bot.get_channel(alerta["canal"])
                mensagem = (
                    "🚨 **ALERTA ATINGIDO**\n"
                    f"{alerta['ativo']} chegou a {preco:.2f}"
                )
                await canal.send(mensagem)
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
            preco = market.preco_atual(ativo)
            await canal.send(f"📈 {ativo} → {preco:.2f}")
        except:
            pass

BR_TZ = pytz.timezone("America/Sao_Paulo")

@tasks.loop(time=time(hour=18, minute=45, tzinfo=BR_TZ))
async def noticias_diarias():

    if not config.NEWS_ATIVAS or not config.CANAL_NOTICIAS:
        return

    canal = bot.get_channel(config.CANAL_NOTICIAS)
    noticias = news.noticias()

    if not noticias:
        return

    # ───── CLASSIFICAÇÃO SIMPLES DO MERCADO ─────
    texto_completo = " ".join(noticias).lower()

    palavras_negativas = ["queda", "cai", "recuo", "tensão", "crise", "volatilidade", "inflação"]
    palavras_positivas = ["alta", "sobe", "ganho", "otimismo", "recuperação", "avanço"]

    score = 0
    for p in palavras_positivas:
        if p in texto_completo:
            score += 1
    for p in palavras_negativas:
        if p in texto_completo:
            score -= 1

    if score >= 2:
        leitura = "🟢 Mercado com viés positivo"
        recomendacao = (
            "📈 **Postura construtiva**\n"
            "• Buscar oportunidades com gestão de risco\n"
            "• Priorizar ativos líquidos\n"
            "• Evitar excesso de alavancagem"
        )
    elif score <= -2:
        leitura = "🔴 Mercado defensivo"
        recomendacao = (
            "⚠️ **Postura defensiva**\n"
            "• Preservar capital\n"
            "• Evitar operações impulsivas\n"
            "• Priorizar proteção e liquidez"
        )
    else:
        leitura = "🟡 Mercado indefinido"
        recomendacao = (
            "⏳ **Postura cautelosa**\n"
            "• Aguardar confirmação de tendência\n"
            "• Operar com menor exposição\n"
            "• Foco em gestão de risco"
        )

    # ───── EMBED JORNAL ─────
    embed = discord.Embed(
        title="🗞️ Jornal do Mercado Global — Abertura",
        color=0xF39C12
    )

    embed.add_field(
        name="🌍 Principais Destaques",
        value="\n".join(f"• {n}" for n in noticias[:5]),
        inline=False
    )

    embed.add_field(
        name="📊 Leitura do Mercado",
        value=leitura,
        inline=False
    )

    embed.add_field(
        name="🧠 Recomendação",
        value=recomendacao,
        inline=False
    )

    embed.set_footer(
        text="Atualizado às 06:00"
    )

    await canal.send(embed=embed)



# ───── START ─────

bot.run(TOKEN)
