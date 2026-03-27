import discord
from discord.ext import commands, tasks
import json, os
from .config import *
from .database import *

intents = discord.Intents.all()
bot = commands.Bot(intents=intents)

def is_admin():
    async def predicate(ctx):
        return any(r.id in ROLES['admins'] for r in ctx.author.roles)
    return commands.check(predicate)

@bot.event
async def on_ready():
    print('🚀 Facção Bot ONLINE!')
    await init_db()
    top_loop.start()
    reset_loop.start()

@bot.event
async def on_member_join(member):
    try:
        e = discord.Embed(title='🎉 BEM-VINDO À FAÇÃO!', 
                         description='**Use /addfarm com admins!\nParticipe PVP!\n!top = Ranking**', 
                         color=0x00ff00)
        await member.send(embed=e)
    except: pass
    
    log = bot.get_channel(CHANNELS['welcome_logs'])
    await log.send(f'➕ **{member}** entrou `ID:{member.id}`')

@bot.event
async def on_member_remove(member):
    log = bot.get_channel(CHANNELS['welcome_logs'])
    await log.send(f'➖ **{member.display_name}** saiu `ID:{member.id}`')

@bot.slash_command(guild_ids=[GUILD_ID])
@is_admin()
async def addfarm(ctx, nome: str, qtd: float, tipo: str = 'un'):
    await add_farm(ctx.author.id, ctx.author.display_name, nome, tipo, qtd)
    
    embed = discord.Embed(title=f'✅ {nome} +{qtd:,.0f}{tipo}', 
                         description=f'**Por:** {ctx.author.mention}\n**{ctx.created_at.strftime("%H:%M %d/%m")}**',
                         color=0x00ff88)
    
    await bot.get_channel(CHANNELS['farm_add']).send(embed=embed)
    await bot.get_channel(CHANNELS['events_farm']).send(f'📈 **{nome}** farmou `{qtd:,.0f} {tipo}`!')
    await ctx.respond('✅ Adicionado!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
@is_admin()
async def addpvp(ctx, nome: str, msg: str):
    eid = await create_pvp(nome, msg)
    embed = discord.Embed(title=f'⚔️ {nome}', description=msg, color=0xff4444)
    embed.set_footer(text=f'Event #{eid}')
    view = PVPView(eid)
    ch = bot.get_channel(CHANNELS['events_pvp'])
    await ch.send(embed=embed, view=view)
    await ctx.respond('⚔️ PVP ativo!', ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID])
async def top(ctx):
    rows = await weekly_top()
    embed = discord.Embed(title='🏆 RANK SEMANAL', color=0xffaa00)
    for i, (name, total) in enumerate(rows, 1):
        medal = '🥇🥈🥉④⑤⑥⑦⑧⑨⑩'[min(i-1, 9)]
        embed.add_field(name=f'{medal} {name}', value=f'{total:,.0f}', inline=False)
    await ctx.respond(embed=embed)

class PVPView(discord.ui.View):
    def __init__(self, eid):
        super().__init__(timeout=86400)
        self.eid = eid

    @discord.ui.button(label='⚔️ PARTICIPAR', style=discord.ButtonStyle.red)
    async def pvp_btn(self, i: discord.Interaction, b: discord.ui.Button):
        if not any(r.id in ROLES['pvp_members'] for r in i.user.roles):
            return await i.response.send('❌ Só PVP!', ephemeral=True)
        await toggle_pvp(self.eid, i.user.id)
        await i.response.send('✅ Participando!', ephemeral=True)

@tasks.loop(hours=6)
async def top_loop():
    rows = await weekly_top(5)
    ch = bot.get_channel(CHANNELS['leaderboard'])
    e = discord.Embed(title='📊 TOP 5 LIVE', color=0x00ff88)
    for i, (n, t) in enumerate(rows):
        e.add_field(name=f'{i+1}. {n}', value=f'{t:,.0f}', inline=True)
    await ch.send(embed=e)

@tasks.loop(hours=168)  # Domingo
async def reset_loop():
    # Reset week + Farm King
    pass  # Add role logic later

bot.run(DISCORD_TOKEN)
