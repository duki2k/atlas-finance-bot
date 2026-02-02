import os, discord, requests, pytz, asyncio
from discord.ext import commands, tasks
from datetime import datetime
import config, market, news, telegram

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

ultimo_manha = None
ultimo_tarde = None

async def log_bot(titulo, mensagem):
    canal = bot.get_channel(config.CANAL_LOGS)
    if canal:
        embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
        embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m %H:%M"))
        await canal.send(embed=embed)

def dolar_para_real():
    try:
        r = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=BRL",timeout=10).json()
        return float(r["rates"]["BRL"])
    except:
        return 5.0

def sentimento(a, q):
    if a > q: return "😄 Mercado positivo"
    if q > a: return "😨 Mercado defensivo"
    return "😐 Mercado neutro"

async def coletar_dados():
    dados = {}
    for categoria, ativos in config.ATIVOS.items():
        dados[categoria] = []
        for ativo in ativos:
            try:
                preco, var = market.dados_ativo(ativo)
                if preco is None or var is None:
                    raise Exception("Sem dados")
                dados[categoria].append((ativo, preco, var))
            except Exception as e:
                await log_bot("Falha ao buscar ativo", f"{ativo}\n{e}")
    return dados

def embed_relatorio(dados, cotacao):
    altas = quedas = 0
    embed = discord.Embed(title="📊 Relatório Completo do Mercado", color=0x3498DB)

    for categoria, itens in dados.items():
        linhas = []
        for ativo, preco, var in itens:
            emoji = "🔼" if var > 0 else "🔽"
            linhas.append(f"`{ativo}` {emoji} {var:.2f}% | ${preco:.2f} / R${preco*cotacao:.2f}")
            altas += var > 0
            quedas += var < 0
        if linhas:
            embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.description = sentimento(altas, quedas)
    embed.set_footer(text="Atlas Finance • Dados reais")
    return embed

def resumo_telegram(dados, label):
    altas = quedas = 0
    texto = f"📊 *Resumo do Mercado — {label}*\n\n"

    for categoria, itens in dados.items():
        texto += f"{categoria}\n"
        for ativo, _, var in itens:
            emoji = "🔼" if var > 0 else "🔽"
            texto += f"• {ativo}: {emoji} {var:.2f}%\n"
            altas += var > 0
            quedas += var < 0
        texto += "\n"

    texto += sentimento(altas, quedas)
    texto += "\n\n— Atlas Finance"
    return texto

async def enviar_relatorios(label):
    dados = await coletar_dados()
    cot = dolar_para_real()

    canal = bot.get_channel(config.CANAL_ANALISE)
    if canal:
        await canal.send(embed=embed_relatorio(dados, cot))

    telegram.enviar_telegram(resumo_telegram(dados, label))

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    scheduler.start()

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await enviar_relatorios("Teste")
    await ctx.send("✅ Teste concluído")

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
