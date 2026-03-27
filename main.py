import discord
from discord.ext import commands
import aiosqlite
import json
from datetime import datetime
import os

# SEUS IDs EXATOS
GUILD_ID = 1486268008266596443
CHANNELS = {
    1486639291739144212: 'admin_cmds',      # comandos-admin
    1486645052653437059: 'farm_add',        # acao-add
    1486642954398466088: 'events_farm',     # evento-farm
    1486268011823366216: 'events_pvp',      # evento-acao
    1486268011823366218: 'leaderboard',     # rank-semanal
    1486268009550188556: 'welcome_logs'     # entradas-saida
}
ROLES = {
    'admins': [1486268008409206867, 1486268008409206864, 1486268008266596449, 1486268008266596448],
    'pvp': [1486268008409206866],
    'farm_king': 1487011323484045462
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print('🚀 FAÇÃO BOT ONLINE!')
    await init_db()

async def init_db():
    async with aiosqlite.connect('faction.db') as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS farms (id INTEGER PRIMARY KEY, admin TEXT, target TEXT, week INT, tipo TEXT, qtd REAL, ts TEXT);
            CREATE TABLE IF NOT EXISTS pvp (id INTEGER PRIMARY KEY, name TEXT, msg TEXT, parts TEXT);
        ''')
        await db.commit()
    print('✅ DB OK')

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title='🎉 BEM-VINDO À FAÇÃO!', description='**/addfarm com admins**\n**PVP events**\n**!top ranking**', color=0x00ff00)
    try:
        await member.send(embed=embed)
    except: pass
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➕ **{member}** `{member.id}` ENTROU')

@bot.event
async def on_member_remove(member):
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➖ **{member.display_name}** `{member.id}` SAIU')

@bot.slash_command(guild_ids=[GUILD_ID])
async def addfarm(ctx, target: str, qtd: float, tipo: str = 'un'):
    if not any(role.id in ROLES['admins'] for role in ctx.author.roles):
        return await ctx.respond('❌ Admin only!', ephemeral=True)
    
    week = datetime.now().isocalendar()[1]
    ts = datetime.now().strftime('%d/%m %H:%M')
    
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO farms VALUES(NULL, ?, ?, ?, ?, ?, ?)', 
                        (ctx.author.name, target, week, tipo, qtd, ts))
        await db.commit()
    
    embed = discord.Embed(title=f'✅ {target} +{qtd:,.0f}{tipo}', color=0x00ff88)
    embed.add_field(name='Admin', value=ctx.author.mention, inline=True)
    embed.set_footer(text=ts)
    
    await bot.get_channel(1486645052653437059).send(embed=embed)  # farm_add
    await bot.get_channel(1486642954398466088).send(f'📈 **{target}** `{qtd:,.0f}{tipo}`!')  # events_farm
    
    await ctx.respond('✅ Logado!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
async def addpvp(ctx, nome: str, msg: str):
    if not any(role.id in ROLES['admins'] for role in ctx.author.roles):
        return await ctx.respond('❌ Admin!', ephemeral=True)
    
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO pvp (name, msg, parts) VALUES(?, ?, \'[]\')', (nome, msg))
        await db.commit()
    
    embed = discord.Embed(title=f'⚔️ {nome}', description=msg, color=0xff4444)
    view = discord.ui.View(timeout=86400)
    button = discord.ui.Button(label='👊 PARTICIPAR', style=discord.ButtonStyle.green)
    view.add_item(button)
    await bot.get_channel(1486268011823366216).send(embed=embed, view=view)  # events_pvp
    await ctx.respond('⚔️ PVP ativo!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
async def top(ctx):
    async with aiosqlite.connect('faction.db') as db:
        week = datetime.now().isocalendar()[1]
        cursor = await db.execute('SELECT target, SUM(qtd) as total FROM farms WHERE week=? GROUP BY target ORDER BY total DESC LIMIT 10', (week,))
        rows = await cursor.fetchall()
    
    embed = discord.Embed(title='🏆 RANK SEMANAL', color=0xffaa00)
    medals = '🥇🥈🥉④⑤⑥⑦⑧⑨⑩'
    for i, (name, total) in enumerate(rows):
        embed.add_field(name=f'{medals[min(i,9)]} {name}', value=f'{total:,.0f}', inline=False)
    await ctx.respond(embed=embed)

bot.run(os.getenv('DISCORD_TOKEN'))
