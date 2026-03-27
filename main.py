import discord
from discord.ext import commands
import aiosqlite
from datetime import datetime
import os

TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

ADMIN_ROLES = [1486268008409206867, 1486268008409206864, 1486268008266596449, 1486268008266596448]

@bot.event
async def on_ready():
    print('✅ FACÇÃO BOT SIMPLES LIVE!')
    await bot.change_presence(activity=discord.Game(name='!farm !top'))

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title='🎉 BEM-VINDO!', description='!farm @nome 500 | !top', color=0x00ff00)
    try:
        await member.send(embed=embed)
    except:
        pass
    print(f'JOIN: {member}')

@bot.event
async def on_member_remove(member):
    print(f'LEAVE: {member}')

@bot.command()
async def farm(ctx, qtd: float, tipo: str = 'un', *, target: str = ''):
    if not any(role.id in ADMIN_ROLES for role in ctx.author.roles):
        await ctx.send('❌ Admin!')
        return
    
    ts = datetime.now().strftime('%H:%M')
    embed = discord.Embed(title=f'✅ {target or ctx.author.name} +{qtd} {tipo}', 
                         description=f'**Admin:** {ctx.author.mention}\n**{ts}**', color=0x00ff88)
    
    await ctx.send(embed=embed)
    print(f'FARM: {target} {qtd} {tipo} by {ctx.author}')

@bot.command()
async def top(ctx):
    await ctx.send('🏆 **TOP SEMANAL** (DB coming soon)')
    print('TOP called')

@bot.command()
async def pvpevent(ctx, *, event: str):
    if not any(role.id in ADMIN_ROLES for role in ctx.author.roles):
        await ctx.send('❌ Admin!')
        return
    
    embed = discord.Embed(title='⚔️ PVP EVENT', description=event, color=0xff4444)
    await ctx.send(embed=embed)
    print(f'PVP: {event}')

bot.run(TOKEN)
