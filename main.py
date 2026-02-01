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

ultimo_analise = None
ultimo_jornal_manha = None
ultimo_jornal_tarde = None

ULTIMOS_PRECOS = {}

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

def admin_channel_only(ctx):
    return config.CANAL_ADMIN and ctx.channel.id == config.CANAL_ADMIN

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
    altas = len([v for v in variacoes if v > 0])
    baixas = len([v for v in variacoes if v < 0])

    if altas > baixas:
        return 0x2ECC71
    elif baixas > altas:
        return 0xE74C3C
    return 0xF1C40F

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

async def log_bot(titulo, mensagem, tipo="INFO"):
    if not config.CANAL_LOGS:
        return

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
        name="🌍 Destaques do Dia",
        value="\n\n".join(f"• {n}" for n in noticias[:6]),
        inline=False
    )

    embed.add_field(
        name="📊 Sentimento do Mercado",
        value=sentimento_mercado(noticias),
        inline=False
    )

    embed.set_footer(text="Atlas Finance Bot • Atualização automática")
    return embed

# ─────────────────────────────
# ENVIO DIRETO (USADO POR TESTE E SCHEDULER)
# ─────────────────────────────

async def enviar_relatorio_agora():
    dados = {}
    cotacao = dolar_para_real()

    for ativo in config.ATIVOS:
        try:
            preco = market.preco_atual(ativo)
            if preco is None or preco == 0:
                await log_bot(
                    "Validação de ativo",
                    f"Preço inválido para `{ativo}`",
                    tipo="AVISO"
                )
                continue

            dados[ativo] = preco

        except Exception as e:
            await log_bot(
                "Validação de ativo",
                f"Falha ao buscar `{ativo}`\n{str(e)}",
                tipo="AVISO"
            )

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


async def enviar_jornal_agora():
    noticias = news.noticias()

    if not noticias:
        await log_bot(
            "Jornal",
            "Nenhuma notícia retornada.",
            tipo="AVISO"
        )
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
# COMANDOS ADMIN
# ─────────────────────────────

@bot.command()
@commands.has_permissions(administrator=True)
async def help(ctx):
    if not admin_channel_only(ctx):
        return

    embed = discord.Embed(
        title="🤖 Atlas Finance Bot — Admin",
        color=0x3498DB
    )

    embed.add_field(
        name="⚙️ Configuração",
        value="`!setcanaladmin`\n`!setcanal`\n`!setcanalnoticias`\n`!setcanallogs`",
        inline=False
    )

    embed.add_field(
        name="🧪 Testes",
        value="`!testenoticias`\n`!testarpublicacoes`\n`!statusbot`\n`!manutencao`",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanaladmin(ctx):
    config.CANAL_ADMIN = ctx.channel.id
    await ctx.send("🔒 Canal admin definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanal(ctx):
    config.CANAL_ANALISE = ctx.channel.id
    await ctx.send("📊 Canal de análises definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanalnoticias(ctx):
    config.CANAL_NOTICIAS = ctx.channel.id
    await ctx.send("📰 Canal de notícias definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcanallogs(ctx):
    config.CANAL_LOGS = ctx.channel.id
    await ctx.send("📋 Canal de logs definido")

@bot.command()
@commands.has_permissions(administrator=True)
async def testenoticias(ctx):
    if not admin_channel_only(ctx):
        return
    await enviar_jornal_agora()
    await ctx.send("📰 Jornal enviado para teste")

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    if not admin_channel_only(ctx):
        return
    await ctx.send("🧪 Enviando publicações manualmente...")
    await enviar_relatorio_agora()
    await enviar_jornal_agora()
    await ctx.send("✅ Publicações enviadas")

@bot.command()
@commands.has_permissions(administrator=True)
async def statusbot(ctx):
    agora = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
    await ctx.send(f"🤖 Bot online • {agora}")

@bot.command()
@commands.has_permissions(administrator=True)
async def manutencao(ctx):
    try:
        market.preco_atual("BTC-USD")
        status = "OK"
    except:
        status = "FALHA"
    await ctx.send(f"🛠️ API de preços: **{status}**")

# ─────────────────────────────
# SCHEDULER CONFIÁVEL (1 MIN)
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_analise, ultimo_jornal_manha, ultimo_jornal_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    # RELATÓRIO 06:00
    if hora == "06:00" and ultimo_analise != agora.date():
        await enviar_relatorio_agora()
        ultimo_analise = agora.date()

    # JORNAL 06:00
    if hora == "06:00" and ultimo_jornal_manha != agora.date():
        await enviar_jornal_agora()
        ultimo_jornal_manha = agora.date()

    # JORNAL 18:00
    if hora == "18:00" and ultimo_jornal_tarde != agora.date():
        await enviar_jornal_agora()
        ultimo_jornal_tarde = agora.date()

# ─────────────────────────────
# START
# ─────────────────────────────

bot.run(TOKEN)
