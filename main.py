import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import json
from datetime import datetime
import os

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = 1486268008266596443
CHANNELS = {
    1486639291739144212: 'admin_cmds',
    1486645052653437059: 'farm_add',
    1486642954398466088: 'events_farm',
    1486268011823366216: 'events_pvp',
    1486268011823366218: 'leaderboard',
    1486268009550188556: 'welcome_logs'
}
ROLES = {
    'admins': [1486268008409206867, 1486268008409206864, 1486268008266596449, 1486268008266596448],
    'pvp': [1486268008409206866]
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

async def init_db():
    async with aiosqlite.connect('faction.db') as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS farms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin TEXT, target TEXT, week INTEGER, tipo TEXT, qtd REAL, ts TEXT
            );
            CREATE TABLE IF NOT EXISTS pvp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, msg TEXT, parts TEXT
            );
        """)
        await db.commit()

@bot.event
async def on_ready():
    print(f'{bot.user} ✅ FAÇÃO BOT LIVE!')
    await init_db()
    print('DB + Bot OK')

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title='🎉 BEM-VINDO À FAÇÃO RP GRAND!', 
                         description='**Commands:**\n• `!farm @nome 500 un`\n• `!top`\n**Fale com admins!**', 
                         color=0x00ff88)
    try:
        await member.send(embed=embed)
        print(f'DM OK: {member}')
    except: print('DM fail')
    
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➕ **{member.display_name}** `{member.id}` **ENTROU**')

@bot.event
async def on_member_remove(member):
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➖ **{member.display_name}** `{member.id}` **SAIU**')

@bot.command()
async def farm(ctx, target: discord.Member, qtd: float, tipo: str = 'un'):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.send('❌ **Admin only!**')
    
    week = datetime.now().isocalendar()[1]
    ts = datetime.now().strftime('%H:%M %d/%m')
    
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO farms (admin, target, week, tipo, qtd, ts) VALUES (?, ?, ?, ?, ?, ?)',
                        (ctx.author.name, target.display_name, week, tipo, qtd, ts))
        await db.commit()
    
    embed = discord.Embed(title=f'✅ {target.display_name} +{qtd:,.0f} {tipo}', color=0x00ff88)
    embed.add_field(name='Por', value=ctx.author.mention)
    embed.set_footer(text=ts)
    
    farm_ch = bot.get_channel(1486645052653437059)
    await farm_ch.send(embed=embed)
    
    event_ch = bot.get_channel(1486642954398466088)
    await event_ch.send(f'📈 **{target.display_name}** farmou `{qtd:,.0f} {tipo}`!')
    
    await ctx.send('✅ **Farm logado!**')

@bot.command()
async def top(ctx):
    async with aiosqlite.connect('faction.db') as db:
        week = datetime.now().isocalendar()[1]
        cursor = await db.execute('SELECT target, SUM(qtd) total FROM farms WHERE week=? GROUP BY target ORDER BY total DESC LIMIT 10', (week,))
        rows = await cursor.fetchall()
    
    embed = discord.Embed(title='🏆 **RANK SEMANAL FARMS**', color=0xffaa00)
    medals = '🥇🥈🥉4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟'
    for i, (name, total) in enumerate(rows):
        embed.add_field(name=f'{medals[min(i,9)]} {name}', value=f'`{total:,.0f}`', inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def pvpevent(ctx, *, event_info: str):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.send('❌ Admin!')
    
    embed = discord.Embed(title='⚔️ **PVP EVENT**', description=event_info, color=0xff4444)
    embed.set_footer(text=f'{ctx.author} | {datetime.now().strftime("%H:%M")}')
    
    view = discord.ui.View(timeout=3600)
    btn = discord.ui.Button(label='👊 PARTICIPAR', style=discord.ButtonStyle.danger)
    view.add_item(btn)
    
    pvp_ch = bot.get_channel(1486268011823366216)
    await pvp_ch.send(embed=embed, view=view)
    await ctx.send('⚔️ **PVP postado!**')

bot.run(TOKEN)
