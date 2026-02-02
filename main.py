import os
import asyncio
import discord
import requests
import pytz
from datetime import datetime
from discord.ext import commands, tasks

import config
import market
import news
import telegram

# ─────────────────────────────
# CONFIGURAÇÕES BÁSICAS
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

# Controle de disparos
ultimo_manha = None
ultimo_tarde = None

# Nome amigável dos ativos
ATIVOS_INFO = {
    # Criptos
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "BNB",
    "XRP-USD": "XRP",
    "ADA-USD": "Cardano",
    "AVAX-USD": "Avalanche",
    "DOT-USD": "Polkadot",
    "LINK-USD": "Chainlink",
    "MATIC-USD": "Polygon",

    # Ações EUA
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL": "Google",
    "NVDA": "Nvidia",
    "META": "Meta",
    "TSLA": "Tesla",
    "BRK-B": "Berkshire Hathaway",
    "JPM": "JP Morgan",
    "V": "Visa",

    # Brasil
    "PETR4.SA": "Petrobras",
    "VALE3.SA": "Vale",
    "ITUB4.SA": "Itaú",
    "BBDC4.SA": "Bradesco",
    "BBAS3.SA": "Banco do Brasil",
    "WEGE3.SA": "Weg",
    "ABEV3.SA": "Ambev",
    "B3SA3.SA": "B3",
    "RENT3.SA": "Localiza",
    "SUZB3.SA": "Suzano",

    # FIIs
    "HGLG11.SA": "HGLG11",
    "XPML11.SA": "XPML11",
    "MXRF11.SA": "MXRF11",
    "VISC11.SA": "VISC11",
    "BCFF11.SA": "BCFF11",
    "KNRI11.SA": "KNRI11",
    "RECT11.SA": "RECT11",
    "HGRE11.SA": "HGRE11",
    "CPTS11.SA": "CPTS11",
    "IRDM11.SA": "IRDM11",

    # ETFs
    "SPY": "SPY",
    "QQQ": "QQQ",
    "VOO": "VOO",
    "IVV": "IVV",
    "VTI": "VTI",
    "DIA": "DIA",
    "IWM": "IWM",
    "EFA": "EFA",
    "VEA": "VEA",
    "VNQ": "VNQ",
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


async def log_bot(titulo, mensagem):
    canal = bot.get_channel(config.CANAL_LOGS)
    if not canal:
        return

    embed = discord.Embed(
        title=f"📋 {titulo}",
        description=mensagem,
        color=0xE67E22
    )
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)


def sentimento_mercado(altas, quedas):
    if altas > quedas:
        return "😄 Mercado positivo"
    if quedas > altas:
        return "😨 Mercado defensivo"
    return "😐 Mercado neutro"


# ─────────────────────────────
# COLETA EM LOTES (CRÍTICO)
# ─────────────────────────────

async def coletar_lote(nome_lote, ativos):
    resultados = []
    for ativo in ativos:
        try:
            preco, variacao = market.dados_ativo(ativo)
            if preco is None or variacao is None:
                await log_bot("Ativo sem dados", f"{ativo} ({nome_lote})")
                continue

            resultados.append((ativo, preco, variacao))
            await asyncio.sleep(0.4)  # anti-bloqueio
        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo}\n{e}")
            await asyncio.sleep(0.6)
    return resultados


async def coletar_dados():
    dados = {}
    total_validos = 0

    for categoria, ativos in config.ATIVOS.items():
        resultados = await coletar_lote(categoria, ativos)
        if resultados:
            dados[categoria] = resultados
            total_validos += len(resultados)

    if total_validos == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}

    return dados


# ─────────────────────────────
# EMBEDS DISCORD
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    altas = quedas = 0
    embed = discord.Embed(
        title="📊 Relatório Completo do Mercado",
        color=0x3498DB
    )

    for categoria, itens in dados.items():
        linhas = []
        for ativo, preco, var in itens:
            nome = ATIVOS_INFO.get(ativo, ativo)
            emoji = "🔼" if var > 0 else "🔽"
            linhas.append(
                f"**{nome}** ({ativo})\n"
                f"{emoji} {var:.2f}% | 💲 ${preco:.2f} | 🇧🇷 R$ {preco*cotacao:.2f}"
            )
            altas += var > 0
            quedas += var < 0

        embed.add_field(
            name=categoria,
            value="\n\n".join(linhas),
            inline=False
        )

    embed.description = sentimento_mercado(altas, quedas)
    embed.set_footer(text="Atlas Finance • Dados reais do mercado")
    return embed


# ─────────────────────────────
# TELEGRAM (RESUMO LONGO)
# ─────────────────────────────

def resumo_telegram(dados, periodo):
    altas = quedas = 0
    texto = f"📊 Resumo do Mercado — {periodo}\n\n"

    for categoria, itens in dados.items():
        texto += f"{categoria}\n"
        for ativo, _, var in itens:
            nome = ATIVOS_INFO.get(ativo, ativo)
            emoji = "🔼" if var > 0 else "🔽"
            texto += f"• {nome}: {emoji} {var:.2f}%\n"
            altas += var > 0
            quedas += var < 0
        texto += "\n"

    texto += sentimento_mercado(altas, quedas)
    texto += "\n\n🧠 Leitura do Bot:\n"

    if altas > quedas:
        texto += "Cenário construtivo, mas com disciplina e gestão de risco."
    elif quedas > altas:
        texto += "Mercado pressionado. Postura defensiva recomendada."
    else:
        texto += "Mercado lateral. Seletividade é fundamental."

    texto += "\n\n— Atlas Finance"
    return texto


# ─────────────────────────────
# ENVIO DE RELATÓRIOS
# ─────────────────────────────

async def enviar_relatorios(periodo):
    dados = await coletar_dados()
    if not dados:
        return

    cot = dolar_para_real()

    canal = bot.get_channel(config.CANAL_ANALISE)
    if canal:
        await canal.send(embed=embed_relatorio(dados, cot))

    telegram.enviar_telegram(resumo_telegram(dados, periodo))


# ─────────────────────────────
# EVENTOS E COMANDOS
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()


@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    await ctx.send(
        "**📌 Comandos disponíveis (Admin):**\n"
        "`!testarpublicacoes` → envia relatório agora\n"
        "`!reiniciar` → reinicia o bot"
    )


@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await enviar_relatorios("Teste Manual")
    await ctx.send("✅ Teste concluído")


@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()


# ─────────────────────────────
# SCHEDULER AUTOMÁTICO
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_manha, ultimo_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_manha != agora.date():
        await enviar_relatorios("Abertura")
        ultimo_manha = agora.date()

    if hora == "18:00" and ultimo_tarde != agora.date():
        await enviar_relatorios("Fechamento")
        ultimo_tarde = agora.date()


bot.run(TOKEN)
