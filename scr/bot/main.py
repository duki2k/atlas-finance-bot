import discord
from discord.ext import commands, tasks
import json
from .config import DISCORD_TOKEN, CHANNELS, ROLES
from .database import *

intents = discord.Intents.default()
intents.members = True  # Para on_member_join/leave
bot = commands.Bot(command_prefix='!', intents=intents)

def is_admin():
    def predicate(ctx):
        return any(role.id in ROLES['admins'] for role in ctx.author.roles)
    return commands.check(predicate)

@bot.event
async def on_ready():
    print(f'{bot.user} v2 online - Facção RP Grand!')
    await init_db()
    weekly_premiacao.start()
    print('✅ DB OK | Logs/Events/Tops ativos')

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(CHANNELS['welcome_logs'])
    embed = discord.Embed(title='👋 Entrada Detectada', color=0x00ff00)
    embed.add_field(name='Membro', value=member.mention, inline=True)
    embed.add_field(name='ID', value=member.id, inline=True)
    embed.timestamp = discord.utils.utcnow()
    await channel.send(embed=embed)
    
    # DM Boas-vindas
    try:
        embed_dm = discord.Embed(title='🎉 Bem-vindo à Facção!', 
                               description='Report farms com admins ou participe de PVP!', color=0x0099ff)
        await member.send(embed=embed_dm)
    except:
        pass

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(CHANNELS['welcome_logs'])
    embed = discord.Embed(title='🚪 Saída Detectada', color=0xff0000)
    embed.add_field(name='Membro', value=member.display_name, inline=True)
    embed.add_field(name='ID', value=member.id, inline=True)
    embed.timestamp = discord.utils.utcnow()
    await channel.send(embed=embed)

@bot.slash_command(guild_ids=[SEU_GUILD_ID])  # Ou global
@is_admin()
async def addfarm(ctx, membro: discord.Member, quantidade: float, tipo: str = 'un'):
    if ctx.channel.id != CHANNELS['addfarms']:
        return await ctx.respond('❌ **Só em #add-farms!**', ephemeral=True)
    
    await add_farm_admin(membro.id, membro.display_name, quantidade, ctx.author.id, tipo)
    embed = discord.Embed(title='✅ Farm Adicionado!', color=0x00ff00)
    embed.add_field(name='Membro', value=membro.mention, inline=True)
    embed.add_field(name='Qtd', value=f'{quantidade:,.0f} {tipo}', inline=True)
    embed.add_field(name='Por', value=ctx.author.mention, inline=True)
    embed.timestamp = discord.utils.utcnow()
    await ctx.respond(embed=embed)

@bot.slash_command()
async def top(ctx):
    top = await get_weekly_top()
    embed = discord.Embed(title='🏆 TOP FARMS SEMANAL', color=0xffaa00)
    medalhas = '🥇🥈🥉⚪⚪⚪⚪⚪⚪⚪'
    for i, (uid, name, total) in enumerate(top):
        embed.add_field(name=f'{medalhas[i]} {name}', value=f'{total:,.0f}', inline=False)
    await ctx.respond(embed=embed)

@bot.slash_command()
@is_admin()
async def relatorio(ctx):
    report = await get_monthly_report(ctx.author.id)
    embed = discord.Embed(title=f'📊 Relatório Mensal - {ctx.author.display_name}', color=0x0099ff)
    for name, total, adds, last_date in report[:10]:
        embed.add_field(name=f'{name} ({adds} adds)', value=f'{total:,.0f} | {last_date}', inline=False)
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command()
@is_admin()
async def createpvp(ctx, titulo: str, descricao: str):
    if ctx.channel.id != CHANNELS['admin_cmds']:
        return await ctx.respond('❌ **Só em #admin-commands!**', ephemeral=True)
    
    event_id = await create_event(titulo, descricao, ctx.author.id)
    embed = discord.Embed(title=titulo, description=descricao, color=0xff4400)
    embed.add_field(name='Criador', value=ctx.author.mention)
    
    view = discord.ui.View(timeout=86400)  # 24h
    async def participate(interaction):
        if any(r.id in ROLES['pvp_members'] for r in interaction.user.roles):
            # Add to participants (simplificado)
            await interaction.response.send_message('✅ Participando!', ephemeral=True)
        else:
            await interaction.response.send_message('❌ **Só membros PVP!**', ephemeral=True)
    
    button = discord.ui.Button(label='🎯 Participar PVP', style=discord.ButtonStyle.green)
    button.callback = participate
    view.add_item(button)
    
    channel = bot.get_channel(CHANNELS['events'])
    await channel.send(embed=embed, view=view)
    await ctx.respond(f'✅ Evento #{event_id} criado!', ephemeral=True)

@bot.slash_command()
@is_admin()
async def resetweek(ctx):
    await reset_week()
    await ctx.respond('🔄 Semana resetada + premiação processada!')

@tasks.loop(hours=168)  # Domingo
async def weekly_premiacao():
    await reset_week()
    top = await get_weekly_top(1)
    if top:
        uid, name, _ = top[0]
        channel = bot.get_channel(CHANNELS['leaderboard'])
        embed = discord.Embed(title='👑 FARM KING DA SEMANA!', description=f'{name} ganhou role!', color=0xff0000)
        await channel.send(embed=embed)

bot.run(DISCORD_TOKEN)
