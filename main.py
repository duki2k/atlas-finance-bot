import discord
from discord.ext import commands
import aiosqlite
from datetime import datetime
import os

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = 1486268008266596443
CHANNELS = {
    1486639291739144212: 'comandos-admin',
    1486645052653437059: 'acao-add',
    1486642954398466088: 'evento-farm',
    1486268011823366216: 'evento-acao',
    1486268011823366218: 'rank-semanal',
    1486268009550188556: 'entradas-saida'
}
ROLES = {
    'admins': [1486268008409206867, 1486268008409206864, 1486268008266596449, 1486268008266596448],
    'pvp': [1486268008409206866]
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} ✅ NOVOS COMANDOS FAÇÃO!')
    await init_db()
    print('✅ DB + FAÇÃO OK')

async def init_db():
    async with aiosqlite.connect('faction.db') as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS farms (
                id INTEGER PRIMARY KEY AUTOINCREMENT, admin TEXT, target TEXT, 
                week INTEGER, tipo TEXT, qtd REAL, ts TEXT
            );
            CREATE TABLE IF NOT EXISTS pvp (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, msg TEXT, parts TEXT
            );
        """)
        await db.commit()

@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title='🎉 BEM-VINDO À FAÇÃO RP GRAND! 🏆',
        description='```\nNOVOS COMANDOS:\n!farm @nome 500 un  (admin)\n!top               (ranking)\n!pvpevent "Guerra" (admin)\n```',
        color=0x00ff88
    )
    try:
        await member.send(embed=embed)
    except: pass
    
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➕ **{member.display_name}** `{member.id}` **ENTROU**')

@bot.event
async def on_member_remove(member):
    log_ch = bot.get_channel(1486268009550188556)
    await log_ch.send(f'➖ **{member.display_name}** `{member.id}` **SAIU**')

@bot.command(name='farm')
async def farm_cmd(ctx, target: discord.Member, qtd: float, tipo: str = 'un'):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.send('❌ **Apenas admins!**')
    
    week = datetime.now().isocalendar()[1]
    ts = datetime.now().strftime('%H:%M %d/%m')
    
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO farms (admin,target,week,tipo,qtd,ts) VALUES (?,?,?,?,?,?)',
                        (ctx.author.display_name, target.display_name, week, tipo, qtd, ts))
        await db.commit()
    
    # Embed confirmação
    embed = discord.Embed(title=f'✅ **{target.display_name}** +{qtd:,.0f} {tipo.upper()}', color=0x00ff88)
    embed.add_field(name='👑 Admin', value=ctx.author.mention, inline=True)
    embed.set_footer(text=f'{ts}')
    
    # Canais específicos
    await bot.get_channel(1486645052653437059).send(embed=embed)  # #acao-add
    await bot.get_channel(1486642954398466088).send(f'📈 **{target.display_name}** farmou `{qtd:,.0f} {tipo}`!')  # #evento-farm
    
    await ctx.send('✅ **Farm registrado!**')

@bot.command(name='top')
async def top_cmd(ctx):
    async with aiosqlite.connect('faction.db') as db:
        week = datetime.now().isocalendar()[1]
        cursor = await db.execute(
            'SELECT target, SUM(qtd) as total FROM farms WHERE week=? GROUP BY target ORDER BY total DESC LIMIT 10', 
            (week,)
        )
        rows = await cursor.fetchall()
    
    if not rows:
        return await ctx.send('📊 **Sem farms esta semana!**')
    
    embed = discord.Embed(title='🏆 **RANKING SEMANAL FARMS**', color=0xffaa00)
    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    for i, (name, total) in enumerate(rows):
        embed.add_field(
            name=f'{medals[i]} **{name}**', 
            value=f'`{total:,.0f}` pontos', 
            inline=False
        )
    embed.timestamp = datetime.now()
    await ctx.send(embed=embed)

@bot.command(name='pvpevent')
async def pvp_cmd(ctx, *, event_info: str):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.send('❌ **Admin only!**')
    
    embed = discord.Embed(
        title='⚔️ **EVENTO PVP CRIADO**', 
        description=event_info, 
        color=0xff4444
    )
    embed.set_footer(text=f'{ctx.author.display_name} | {datetime.now().strftime("%H:%M")}')
    
    # Simples reaction (sem view timeout issues)
    msg = await bot.get_channel(1486268011823366216).send(embed=embed)  # #evento-acao
    await msg.add_reaction('👊')
    
    await ctx.send(f'⚔️ **PVP postado em #evento-acao!**')

@bot.command(name='reset')
async def reset_cmd(ctx):
    if not any(r.id in ROLES['admins'] for r in ctx.author.roles):
        return await ctx.send('❌ Admin!')
    
    cutoff_week = datetime.now().isocalendar()[1] - 4
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('DELETE FROM farms WHERE week < ?', (cutoff_week,))
        await db.commit()
    
    await ctx.send('🔄 **Semana resetada!**')

bot.run(TOKEN)
