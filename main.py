import os
import asyncio
import discord
import requests
import pytz
from datetime import datetime, timedelta
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
        )
        r.raise_for_status()
        data = r.json()
        rate = data.get("rates", {}).get("BRL")
        if rate is None:
            return 5.0
        return float(rate)
    except (requests.RequestException, ValueError, TypeError):
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
@@ -301,55 +306,79 @@ async def comandos(ctx):
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
    try:
        await enviar_publicacoes("Teste Manual")
    except Exception as exc:
        await log_bot("Erro no teste manual", f"{exc}")
        await ctx.send("❌ Falha no teste. Verifique os logs.")
        return
    await ctx.send("✅ Teste finalizado")

@bot.command()
@commands.has_permissions(administrator=True)
async def reiniciar(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await asyncio.sleep(2)
    await bot.close()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar este comando.")
        return
    await log_bot("Erro em comando", str(error))

# ─────────────────────────────
# SCHEDULER (06h / 18h)
# ─────────────────────────────

def _deve_disparar(agora, hora_alvo, ultima_execucao):
    alvo = agora.replace(
        hour=hora_alvo,
        minute=0,
        second=0,
        microsecond=0
    )
    if ultima_execucao == agora.date():
        return False
    if agora < alvo:
        return False
    return (agora - alvo) <= timedelta(hours=6)

@tasks.loop(minutes=1)
async def scheduler():
    global ultimo_manha, ultimo_tarde

    agora = datetime.now(BR_TZ)

    if _deve_disparar(agora, 6, ultimo_manha):
        await enviar_publicacoes("Abertura (06:00)")
        ultimo_manha = agora.date()

    if _deve_disparar(agora, 18, ultimo_tarde):
        await enviar_publicacoes("Fechamento (18:00)")
        ultimo_tarde = agora.date()

bot.run(TOKEN)
