import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1486268008266596443
WELCOME_LOG_CHANNEL_ID = 1486268009550188556
RANKING_CHANNEL_ID = 1486268011823366218
DB_FILE = "faction.db"

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

def get_week_key():
    now = datetime.now()
    year, week, _ = now.isocalendar()
    return f"{year}-W{week}"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_key TEXT NOT NULL,
            membro TEXT NOT NULL,
            farm_tipo TEXT NOT NULL,
            qtd REAL NOT NULL,
            admin_id INTEGER NOT NULL,
            admin_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def add_farm(membro: str, farm_tipo: str, qtd: float, admin_id: int, admin_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO farms (week_key, membro, farm_tipo, qtd, admin_id, admin_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        get_week_key(),
        membro,
        farm_tipo,
        qtd,
        admin_id,
        admin_name,
        datetime.now().strftime("%d/%m/%Y %H:%M")
    ))
    conn.commit()
    conn.close()

def get_top_ranking(limit=10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT membro, SUM(qtd) as total
        FROM farms
        WHERE week_key = ?
        GROUP BY membro
        ORDER BY total DESC
        LIMIT ?
    """, (get_week_key(), limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_farm_breakdown(limit=10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT membro,
               SUM(CASE WHEN farm_tipo = 'Pedra' THEN qtd ELSE 0 END) as pedra,
               SUM(CASE WHEN farm_tipo = 'Semente' THEN qtd ELSE 0 END) as semente,
               SUM(qtd) as total
        FROM farms
        WHERE week_key = ?
        GROUP BY membro
        ORDER BY total DESC
        LIMIT ?
    """, (get_week_key(), limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"{bot.user} online com sucesso!")
        print(f"{len(synced)} slash commands sincronizados.")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

    await bot.change_presence(activity=discord.Game(name="/farm | /previewtop | /fechamento | /tutorial"))

@bot.event
async def on_member_join(member):
    try:
        embed = discord.Embed(
            title="🎉 Bem-vindo à facção!",
            description="Use `/tutorial` para aprender os comandos disponíveis.",
            color=0x00FF88
        )
        embed.add_field(
            name="Comandos",
            value="`/tutorial`",
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
    farm="Escolha o tipo de farm"
)
@app_commands.choices(farm=[
    app_commands.Choice(name="Pedra", value="Pedra"),
    app_commands.Choice(name="Semente", value="Semente"),
])
async def farm(
    interaction: discord.Interaction,
    membro: str,
    qtd: float,
    farm: app_commands.Choice[str]
):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Apenas admins podem usar esse comando.",
            ephemeral=True
        )
        return

    add_farm(
        membro=membro,
        farm_tipo=farm.value,
        qtd=qtd,
        admin_id=interaction.user.id,
        admin_name=interaction.user.display_name
    )

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed = discord.Embed(
        title="✅ Farm registrado",
        color=0x00FF88
    )
    embed.add_field(name="Membro", value=membro, inline=False)
    embed.add_field(name="Farm desejado", value=farm.value, inline=True)
    embed.add_field(name="Quantidade", value=f"{qtd} un", inline=True)
    embed.add_field(name="Adicionado por", value=interaction.user.mention, inline=False)
    embed.set_footer(text=f"Registrado em {agora}")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="previewtop", description="Ver ranking privado antes do fechamento", guild=guild_obj)
async def previewtop(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Apenas admins podem usar esse comando.",
            ephemeral=True
        )
        return

    rows = get_farm_breakdown(limit=10)

    if not rows:
        await interaction.response.send_message(
            "📭 Ainda não há farms registrados nesta semana.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🔒 Preview do ranking semanal",
        description="Visualização privada antes do fechamento oficial.",
        color=0xF1C40F
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, (membro, pedra, semente, total) in enumerate(rows):
        embed.add_field(
            name=f"{medals[i]} {membro}",
            value=f"Pedra: {pedra:.0f} un\nSemente: {semente:.0f} un\nTotal: {total:.0f} un",
            inline=False
        )

    embed.set_footer(text=f"Semana atual: {get_week_key()}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="fechamento", description="Publicar ranking semanal no canal oficial", guild=guild_obj)
async def fechamento(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ Apenas admins podem usar esse comando.",
            ephemeral=True
        )
        return

    rows = get_farm_breakdown(limit=10)

    if not rows:
        await interaction.response.send_message(
            "📭 Não há farms registrados para publicar nesta semana.",
            ephemeral=True
        )
        return

    ranking_channel = interaction.guild.get_channel(RANKING_CHANNEL_ID)
    if ranking_channel is None:
        await interaction.response.send_message(
            "❌ Não encontrei o canal de ranking configurado.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🏆 Fechamento semanal de farms",
        description=f"Resultado oficial da semana `{get_week_key()}`.",
        color=0xE67E22
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, (membro, pedra, semente, total) in enumerate(rows):
        embed.add_field(
            name=f"{medals[i]} {membro}",
            value=f"Pedra: {pedra:.0f} un\nSemente: {semente:.0f} un\nTotal: {total:.0f} un",
            inline=False
        )

    embed.set_footer(text=f"Publicado por {interaction.user.display_name}")
    await ranking_channel.send(embed=embed)

    await interaction.response.send_message(
        f"✅ Fechamento publicado com sucesso em {ranking_channel.mention}.",
        ephemeral=True
    )

@bot.tree.command(name="tutorial", description="Aprender a usar o bot", guild=guild_obj)
async def tutorial(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📘 Tutorial do Bot da Facção",
        description="Guia rápido de uso dos comandos oficiais.",
        color=0x3498DB
    )

    embed.add_field(
        name="/farm",
        value=(
            "Registra um farm para um membro.\n"
            "Uso: `/farm membro:Nome qtd:500 farm:Pedra`\n"
            "Uso: `/farm membro:Nome qtd:500 farm:Semente`\n"
            "Somente admins podem usar."
        ),
        inline=False
    )
    embed.add_field(
        name="/previewtop",
        value="Mostra um ranking privado apenas para admins, antes do fechamento oficial.",
        inline=False
    )
    embed.add_field(
        name="/fechamento",
        value="Publica o ranking semanal no canal oficial configurado. Somente admins podem usar.",
        inline=False
    )
    embed.add_field(
        name="Como funciona",
        value=(
            "1. Admins registram os farms com `/farm`.\n"
            "2. Admins consultam previamente com `/previewtop`.\n"
            "3. Quando quiser, o admin executa `/fechamento`.\n"
            "4. O bot publica o resultado no canal oficial de ranking."
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
