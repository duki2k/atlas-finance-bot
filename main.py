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

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

ultimo_manha = None
ultimo_tarde = None

# ─────────────────────────────
# UTIL
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
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

def sentimento(altas, quedas):
    if altas > quedas:
        return "😄 Mercado positivo", 0x2ECC71
    if quedas > altas:
        return "😨 Mercado defensivo", 0xE74C3C
    return "😐 Mercado neutro", 0xF1C40F

def emoji_var(v):
    if v is None:
        return "⏺️"
    if v > 0:
        return "🔼"
    if v < 0:
        return "🔽"
    return "⏺️"

def texto_cenario(sent_label):
    if "positivo" in sent_label:
        return (
            "🧭 **Cenário:** apetite por risco maior.\n"
            "✅ Foque em qualidade e tendência.\n"
            "⚠️ Evite exagerar na alavancagem."
        )
    if "defensivo" in sent_label:
        return (
            "🧭 **Cenário:** aversão a risco.\n"
            "🛡️ Priorize proteção, caixa e ativos mais resilientes.\n"
            "🎯 Procure entradas apenas com confirmação."
        )
    return (
        "🧭 **Cenário:** mercado lateral/indefinido.\n"
        "🎯 Seja seletivo e opere menor.\n"
        "⏳ Espere direção antes de aumentar exposição."
    )

def ideias_em_baixa_educacional():
    # Educação — sem recomendar ativo específico
    return (
        "💡 **Se o dia estiver em baixa (educacional):**\n"
        "• Prefira **qualidade** (empresas grandes e lucrativas)\n"
        "• Busque **ETFs amplos** (diversificação)\n"
        "• Avalie **setores defensivos** (consumo básico, saúde)\n"
        "• Pense em **aportes fracionados** (compras em etapas)\n"
        "• Mantenha **liquidez** e evite entrar “no impulso”"
    )

# ─────────────────────────────
# COLETA EM LOTES
# ─────────────────────────────

async def coletar_lote(categoria, ativos, delay=0.35):
    itens = []
    for ativo in ativos:
        try:
            p, v = market.dados_ativo(ativo)
            if p is None or v is None:
                await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
            else:
                itens.append((ativo, p, v))
        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo} ({categoria})\n{e}")
        await asyncio.sleep(delay)
    return itens

async def coletar_dados():
    dados = {}
    total = 0
    for categoria, ativos in config.ATIVOS.items():
        lote = await coletar_lote(categoria, ativos)
        if lote:
            dados[categoria] = lote
            total += len(lote)

    if total == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}
    return dados

# ─────────────────────────────
# DISCORD EMBEDS
# ─────────────────────────────

def embed_relatorio(dados, cotacao):
    altas = 0
    quedas = 0

    # top moves geral
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, var))

    top_alta = sorted(moves, key=lambda x: x[1], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[1])[:3]

    sent_label, cor = sentimento(
        sum(1 for _, v in moves if v > 0),
        sum(1 for _, v in moves if v < 0)
    )

    embed = discord.Embed(
        title="📊 Relatório Completo do Mercado",
        description=f"{sent_label}\n\n{texto_cenario(sent_label)}",
        color=cor
    )

    if top_alta:
        embed.add_field(
            name="🔝 Top 3 Altas",
            value="\n".join(f"• `{a}` {emoji_var(v)} {v:.2f}%" for a, v in top_alta),
            inline=False
        )
    if top_baixa:
        embed.add_field(
            name="🔻 Top 3 Quedas",
            value="\n".join(f"• `{a}` {emoji_var(v)} {v:.2f}%" for a, v in top_baixa),
            inline=False
        )

    for categoria, itens in dados.items():
        linhas = []
        for ativo, preco, var in itens:
            linhas.append(
                f"`{ativo}` {emoji_var(var)} {var:.2f}%  |  💲 {preco:,.2f}  |  🇧🇷 R$ {(preco*cotacao):,.2f}"
            )
        embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.set_footer(text="Atlas Finance • Dados reais (com fallback)")

    return embed

def embed_jornal(noticias, periodo):
    embed = discord.Embed(
        title=f"🗞️ Jornal do Mercado — {periodo}",
        description="🌍 Principais manchetes e impactos no mercado",
        color=0x00BFFF
    )
    if noticias:
        embed.add_field(
            name="🔥 Manchetes (mundo)",
            value="\n\n".join(f"📰 {n}" for n in noticias[:8]),
            inline=False
        )
    else:
        embed.add_field(
            name="⚠️ Sem manchetes",
            value="O RSS não retornou resultados agora. Tentaremos novamente no próximo ciclo.",
            inline=False
        )
    embed.set_footer(text="Fontes: Google News RSS")
    return embed

# ─────────────────────────────
# TELEGRAM (MAIS BONITO)
# ─────────────────────────────

def telegram_resumo(dados, noticias, periodo):
    moves = []
    for categoria, itens in dados.items():
        for ativo, preco, var in itens:
            moves.append((ativo, preco, var))

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, _ = sentimento(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    txt = []
    txt.append(f"📊 *Resumo do Mercado — {periodo}*")
    txt.append(f"{sent_label}")
    txt.append("")
    txt.append(texto_cenario(sent_label).replace("**", "").replace("•", "-"))
    txt.append("")

    if top_alta:
        txt.append("🔝 Top 3 Altas")
        for a, _, v in top_alta:
            txt.append(f"- {a} {emoji_var(v)} {v:.2f}%")
        txt.append("")

    if top_baixa:
        txt.append("🔻 Top 3 Quedas")
        for a, _, v in top_baixa:
            txt.append(f"- {a} {emoji_var(v)} {v:.2f}%")
        txt.append("")

    # manchetes
    if noticias:
        txt.append("🌍 Manchetes do mundo (impactos)")
        for n in noticias[:6]:
            txt.append(f"📰 {n}")
        txt.append("")
    else:
        txt.append("🌍 Manchetes do mundo")
        txt.append("📰 (sem manchetes disponíveis agora)")
        txt.append("")

    # educativo
    txt.append(ideias_em_baixa_educacional())
    txt.append("")
    txt.append("— Atlas Finance")

    # Telegram.py está sem parse_mode. Mantém texto simples.
    return "\n".join(txt)

# ─────────────────────────────
# ENVIO
# ─────────────────────────────

async def enviar_publicacoes(periodo):
    dados = await coletar_dados()
    if not dados:
        return

    cot = dolar_para_real()
    manchetes = news.noticias()

    # Discord: relatório
    canal_analise = bot.get_channel(config.CANAL_ANALISE)
    if canal_analise:
        await canal_analise.send(embed=embed_relatorio(dados, cot))

    # Discord: jornal
    canal_news = bot.get_channel(config.CANAL_NOTICIAS)
    if canal_news:
        await canal_news.send(embed=embed_jornal(manchetes, periodo))
    else:
        await log_bot("CANAL_NOTICIAS inválido", "Não encontrei o canal de notícias no Discord.")

    # Telegram: resumo com notícias
    ok = telegram.enviar_telegram(telegram_resumo(dados, manchetes, periodo))
    if not ok:
        await log_bot("Telegram", "Falha ao enviar mensagem (token/chat_id/permissão).")

    # log se RSS vier vazio
    if not manchetes:
        await log_bot("RSS vazio", "news.noticias() retornou lista vazia (pode ser temporário).")

# ─────────────────────────────
# EVENTOS E COMANDOS
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"🤖 Conectado como {bot.user}")
    if not scheduler.is_running():
        scheduler.start()

@bot.command(name="comandos")
@commands.has_permissions(administrator=True)
async def comandos(ctx):
    embed = discord.Embed(
        title="🤖 Atlas Finance — Comandos",
        description="Acesso restrito a administradores",
        color=0x5865F2
    )
    embed.add_field(
        name="🧪 Testes",
        value="`!testarpublicacoes` → envia relatório + jornal + telegram agora",
        inline=False
    )
    embed.add_field(
        name="⏱️ Automático",
        value="06:00 e 18:00 (relatório + jornal + telegram)",
        inline=False
    )
    embed.add_field(
        name="⚙️ Sistema",
        value="`!reiniciar` → reinicia o bot",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def testarpublicacoes(ctx):
    await ctx.send("🧪 Disparando publicações...")
    await enviar_publicacoes("Teste Manual")
    await ctx.send("✅ Teste finalizado")

@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()

# ─────────────────────────────
# SCHEDULER (06h / 18h)
# ─────────────────────────────

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_manha, ultimo_tarde

    agora = datetime.now(BR_TZ)
    hora = agora.strftime("%H:%M")

    if hora == "06:00" and ultimo_manha != agora.date():
        await enviar_publicacoes("Abertura (06:00)")
        ultimo_manha = agora.date()

    if hora == "18:00" and ultimo_tarde != agora.date():
        await enviar_publicacoes("Fechamento (18:00)")
        ultimo_tarde = agora.date()

bot.run(TOKEN)
