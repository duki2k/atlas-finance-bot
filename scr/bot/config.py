import os
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# 👇 SEUS IDs AQUI 👇
CHANNELS = {
    'welcome_logs': 1486268009550188556,  # #welcome-logs
    'admin_cmds': 1486639291739144212,    # #admin-cmds
    'add_farms': 1486642954398466088,     # #add-farms (admin only)
    'pvp_events': 1486645052653437059,    # #pvp-events
    'leaderboard': 1486268011823366218
}

ROLES = {
    'admin': [1486268008409206867, 1486268008409206866, 1486268008409206864],
    'pvp_member': 1486268008266596448,   # Para participar PVP
    'farm_king': 1486268008409206864
}
