import os
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1486268008266596443
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
guild_obj = discord.Object(id=GUILD_ID)

def is_admin(member: discord.Member) -> bool:
    return any(role.id in ADMIN_ROLES for role in member.roles)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"{bot.user} online com sucesso!")
        print(f"{len(synced)} slash commands sincronizados.")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

    await bot.change_presence(activity=discord.Game(name="/farm | /top | /pvpevent | /tutorial"))

@bot.event
async def on_member_join(member):
    try:
        embed = discord.Embed(
            title="🎉 Bem-vindo à facção!",
            description="Use `/tutorial` para aprender todos os comandos do bot.",
            color=0x00FF88
        )
        embed.add_field(
            name="Comandos principais",
            value="`/farm` ` /top` ` /pvpevent` ` /tutorial`",
            inline=False
        )
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

@bot.tree.command(name="farm", description="Registrar um farm para um membro", guild=guild_obj)
@app_commands.describe(
    membro="Nome do membro que recebeu o farm",
    qtd="Quantidade farmada",
    tipo="Tipo do farm, ex: un, k, pts"
)
async def farm(interaction: discord.Interaction, membro: str, qtd: float, tipo: str = "un"):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("❌ Apenas admins podem usar esse comando.", ephemeral=True)
        return

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="✅ Farm registrado",
        description=(
            f"**Membro:** {membro}\n"
            f"**Quantidade:** {qtd}\n"
            f"**Tipo:** {tipo}\n"
            f"**Adicionado por:** {interaction.user.mention}"
        ),
        color=0x00FF88
    )
    embed.set_footer(text=f"Registrado em {agora}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="top", description="Mostrar ranking semanal", guild=guild_obj)
async def top(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 Ranking semanal",
        description="O ranking com banco de dados será adicionado na próxima etapa estável.",
        color=0xFFAA00
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="pvpevent", description="Criar um evento PVP", guild=guild_obj)
@app_commands.describe(mensagem="Descrição do evento PVP")
async def pvpevent(interaction: discord.Interaction, mensagem: str):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("❌ Apenas admins podem usar esse comando.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚔️ Evento PVP",
        description=mensagem,
        color=0xFF4444
    )
    embed.set_footer(text=f"Criado por {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("👊")

@bot.tree.command(name="tutorial", description="Aprender a usar o bot", guild=guild_obj)
async def tutorial(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📘 Tutorial do Bot da Facção",
        description="Guia rápido para usar os comandos em barra do servidor.",
        color=0x3498DB
    )

    embed.add_field(
        name="/farm",
        value="Registra um farm. Uso: `/farm membro:Nome qtd:500 tipo:un` (somente admin).",
        inline=False
    )
    embed.add_field(
        name="/top",
        value="Mostra o ranking semanal atual.",
        inline=False
    )
    embed.add_field(
        name="/pvpevent",
        value="Cria um evento PVP. Uso: `/pvpevent mensagem:Guerra no QG às 20h` (somente admin).",
        inline=False
    )
    embed.add_field(
        name="/tutorial",
        value="Mostra este guia sempre que alguém precisar aprender os comandos.",
        inline=False
    )
    embed.add_field(
        name="Observações",
        value=(
            "- Digite `/` no chat para ver os comandos.\n"
            "- Alguns comandos são exclusivos para admins.\n"
            "- O bot também envia mensagem de boas-vindas por DM."
        ),
        inline=False
    )

    embed.set_footer(text="Tutorial oficial do bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
