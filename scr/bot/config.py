import os
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = 1486268008266596443  # Seu server

CHANNELS = {
    'admin_cmds': 1486639291739144212,      # #comandos-admin
    'farm_add': 1486645052653437059,        # #acao-add  
    'events_farm': 1486642954398466088,     # #evento-farm
    'events_pvp': 1486268011823366216,      # #evento-acao
    'leaderboard': 1486268011823366218,     # #rank-semanal
    'welcome_logs': 1486268009550188556     # #entradas-saida
}

ROLES = {
    'farm_king': 1487011323484045462,           # Oposição da semana
    'pvp_members': [1486268008409206866],       # PVP cargos
    'admins': [
        1486268008409206867,  # Cúpula
        1486268008409206864,
        1486268008266596449,
        1486268008266596448
    ]
}
