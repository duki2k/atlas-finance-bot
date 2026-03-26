import discord
from discord.ext import commands, tasks
from .config import DISCORD_TOKEN, CHANNELS, ROLES
from .database import init_db, add_farm, get_weekly_top, get_user_farms, reset_week
import asyncio

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} pronto na facção RP Grand!')
    await init_db()
    weekly_tasks.start()
    if not leaderboard_loop.is_running():
        leaderboard_loop.start()
    print('DB init OK | Tasks rodando')

@bot.command(name='farm')
async def cmd_farm(ctx, quantidade: float, *, tipo: str = 'cash'):
    if ctx.channel.id != CHANNELS['reports']:
        return await ctx.send('❌ **Apenas em #farm-reports!**')
    
    await add_farm(ctx.author.id, ctx.author.display_name, tipo, quantidade)
    embed = discord.Embed(
        title='✅ Farm Registrado!',
        description=f'{ctx.author.mention} entregou **{quantidade:,.0f} {tipo.upper()}** esta semana!',
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.command(name='top', aliases=['lb', 'ranking'])
async def cmd_top(ctx):
    top = await get_weekly_top(10)
    embed = discord.Embed(title='🏆 **TOP FARMS SEMANAL**', color=0xffaa00)
    medalhas = ['🥇', '🥈', '🥉', '⚪', '⚪']
    
    for i, (uid, name, total) in enumerate(top):
        medal = medalhas[min(i, 4)]
        embed.add_field(
            name=f'{medal} {i+1}. {name}',
            value=f'**{total:,.0f}** totais',
            inline=False
        )
    embed.set_footer(text='Semana atual | !meusfarms para seus stats')
    await ctx.send(embed=embed)

@bot.command(name='meusfarms', aliases=['me'])
async def cmd_mine(ctx):
    farms = await get_user_farms(ctx.author.id)
    if not farms:
        return await ctx.send('📊 **Sem farms esta semana ainda!** Use `!farm`')
    
    embed = discord.Embed(title=f'📈 Farms de {ctx.author.display_name}', color=0x0099ff)
    total = 0
    for tipo, qtd in farms:
        embed.add_field(name=tipo.upper(), value=f'{qtd:,.0f}', inline=True)
        total += qtd
    embed.set_footer(text=f'Total semana: {total:,.0f}')
    await ctx.send(embed=embed)

@bot.command(name='resetweek')
@commands.has_role(ROLES['admin'])
async def cmd_reset(ctx):
    await reset_week()
    await ctx.send('🔄 **Semana resetada!** Leaderboard limpo.')

@tasks.loop(hours=168)  # 1 semana
async def weekly_tasks():
    """Reset + Premiação"""
    await reset_week()
    channel = bot.get_channel(CHANNELS['leaderboard'])
    top = await get_weekly_top(1)
    if top:
        uid, name, _ = top[0]
        # Role auto (descomente após ID correto)
        # role = discord.utils.get(ctx.guild.roles, id=ROLES['farm_king'])
        # member = bot.get_user(uid)
        # await member.add_roles(role)
        embed = discord.Embed(title='👑 **FARM KING DA SEMANA!**', description=f'{name} dominou!', color=0xff0000)
        await channel.send(embed=embed)

@tasks.loop(hours=6)  # Leaderboard a cada 6h
async def leaderboard_loop():
    channel = bot.get_channel(CHANNELS['leaderboard'])
    top = await get_weekly_top(3)
    embed = discord.Embed(title='📊 **LIVE LEADERBOARD**', color=0x00ff00)
    for i, (uid, name, total) in enumerate(top):
        emoji = '🥇🥈🥉'[i]
        embed.add_field(name=f'{emoji} {name}', value=f'{total:,.0f}', inline=True)
    await channel.send(embed=embed)

bot.run(DISCORD_TOKEN)
