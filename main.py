import discord
from discord.ext import commands
from datetime import datetime
import os

TOKEN = os.getenv("DISCORD_TOKEN")

WELCOME_LOG_CHANNEL_ID = 1486268009550188556
ADMIN_ROLES = [
    1486268008409206867,
    1486268008409206864,
    1486268008266596449,
    1486268008266596448
]

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def is_admin(member):
    return any(role.id in ADMIN_ROLES for role in member.roles)

@bot.event
async def on_ready():
    print(f"{bot.user} online com sucesso!")
    await bot.change_presence(activity=discord.Game(name="!farm | !top | !pvpevent"))

@bot.event
async def on_member_join(member):
    try:
        embed = discord.Embed(
            title="🎉 Bem-vindo à facção!",
            description="Use os canais da facção e fale com a administração para registrar farms e participar dos eventos.",
            color=0x00FF88
        )
        embed.add_field(name="Comandos", value="`!farm` `!top` `!pvpevent`", inline=False)
        embed.set_footer(text="Mensagem automática de boas-vindas")
        await member.send(embed=embed)
    except:
        pass

    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        await channel.send(f"➕ **Entrada:** {member.mention} | `{member.id}`")

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        await channel.send(f"➖ **Saída:** {member.display_name} | `{member.id}`")

@bot.command()
async def farm(ctx, qtd: float, tipo: str = "un", *, nome: str = None):
    if not is_admin(ctx.author):
        await ctx.send("❌ Apenas admins podem usar esse comando.")
        return

    alvo = nome if nome else ctx.author.display_name
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="✅ Farm registrado",
        description=f"**Membro:** {alvo}\n**Quantidade:** {qtd}\n**Tipo:** {tipo}\n**Adicionado por:** {ctx.author.mention}",
        color=0x00FF88
    )
    embed.set_footer(text=f"Registrado em {agora}")
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    embed = discord.Embed(
        title="🏆 Ranking semanal",
        description="O ranking com banco de dados será adicionado na próxima etapa estável.",
        color=0xFFAA00
    )
    await ctx.send(embed=embed)

@bot.command()
async def pvpevent(ctx, *, mensagem: str):
    if not is_admin(ctx.author):
        await ctx.send("❌ Apenas admins podem usar esse comando.")
        return

    embed = discord.Embed(
        title="⚔️ Evento PVP",
        description=mensagem,
        color=0xFF4444
    )
    embed.set_footer(text=f"Criado por {ctx.author.display_name}")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("👊")

bot.run(TOKEN)
