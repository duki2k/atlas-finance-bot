import discord
from discord.ext import commands, tasks
import aiosqlite
import json
import os
from datetime import datetime

# SEUS IDs (confirmados)
GUILD_ID = 1486268008266596443
CHANNELS = {
    'admin_cmds': 1486639291739144212,
    'farm_add': 1486645052653437059,
    'events_farm': 1486642954398466088,
    'events_pvp': 1486268011823366216,
    'leaderboard': 1486268011823366218,
    'welcome_logs': 1486268009550188556
}
ROLES = {
    'admins': [1486268008409206867, 1486268008409206864, 1486268008266596449, 1486268008266596448],
    'pvp': [1486268008409206866],
    'farm_king': 1487011323484045462
}

TOKEN = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

async def init_db():
    async with aiosqlite.connect('data.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS farms (id INTEGER PRIMARY KEY, admin TEXT, target TEXT, week INT, tipo TEXT, qtd REAL, ts TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS pvp (id INTEGER PRIMARY KEY, name TEXT, msg TEXT, parts TEXT)''')
        await db.commit()

@bot.event
async def on_ready():
    print(f'{bot.user} ✅ Facção Bot LIVE!')
    await init_db()
    print('DB OK')

@bot.event
async def on_member_join(member):
    try:
        embed = discord.Embed(title='🎉 BEM-VINDO À FAÇÃO RP GRAND!', color=0x00ff00)
        embed.description = '```Reporte farms com /addfarm!\nParticipe PVP events!\n!top = Ranking semanal```'
        await member.send(embed=embed)
    except: pass
    
    log_ch = bot.get_channel(CHANNELS['welcome_logs'])
    await log_ch.send(f'➕ **{member.display_name}** `{member.id}` ENTRADA')

@bot.event
async def on_member_remove(member):
    log_ch = bot.get_channel(CHANNELS['welcome_logs'])
    await log_ch.send(f'➖ **{member.display_name}** `{member.id}` SAÍDA')

@bot.slash_command(guild_ids=[GUILD_ID])
async def addfarm(ctx, target: str, qtd: float, tipo: str = 'un'):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.respond('❌ **Admin only!**', ephemeral=True)
    
    week = datetime.now().isocalendar()[1]
    ts = datetime.now().strftime('%d/%m %H:%M')
    async with aiosqlite.connect('data.db') as db:
        await db.execute('INSERT INTO farms VALUES (NULL, ?, ?, ?, ?, ?, ?)', 
                        (ctx.author.name, target, week, tipo, qtd, ts))
        await db.commit()
    
    embed = discord.Embed(title=f'✅ {target} +{qtd:,.0f} {tipo}', color=0x00ff88)
    embed.add_field(name='Por', value=ctx.author.mention)
    embed.set_footer(text=ts)
    
    await bot.get_channel(CHANNELS['farm_add']).send(embed=embed)
    await bot.get_channel(CHANNELS['events_farm']).send(f'📈 **{target}** farmou `{qtd:,.0f}{tipo}`!')
    await ctx.respond('✅ Farm logado!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
async def addpvp(ctx, nome: str, msg: str):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.respond('❌ Admin!', ephemeral=True)
    
    async with aiosqlite.connect('data.db') as db:
        await db.execute('INSERT INTO pvp (name, msg, parts) VALUES (?, ?, \'[]\')', (nome, msg))
        await db.commit()
    
    embed = discord.Embed(title=f'⚔️ **{nome}**', description=msg, color=0xff4444)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label='PARTICIPAR', style=discord.ButtonStyle.green, custom_id='pvp'))
    ch = bot.get_channel(CHANNELS['events_pvp'])
    await ch.send(embed=embed, view=view)
    await ctx.respond('⚔️ PVP enviado!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
async def top(ctx):
    async with aiosqlite.connect('data.db') as db:
        week = datetime.now().isocalendar()[1]
        cursor = await db.execute('SELECT target, SUM(qtd) t FROM farms WHERE week=? GROUP BY target ORDER BY t DESC LIMIT 10', (week,))
        rows = await cursor.fetchall()
    
    embed = discord.Embed(title='🏆 RANK FARMS', color=0xffaa00)
    for i, (name, total) in enumerate(rows):
        medal = '🥇🥈🥉④⑤⑥⑦⑧⑨⑩'[i]
        embed.add_field(name=f'{medal} {name}', value=f'{total:,.0f}', inline=False)
    await ctx.respond(embed=embed)

bot.run(TOKEN)
