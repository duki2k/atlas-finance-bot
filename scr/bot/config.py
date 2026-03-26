import os
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Adicione no Railway

# 👇 EDIITE Estes IDs dos seus canais/roles Discord 👇
CHANNELS = {
    'reports': 1234567890123456789,     # ID #farm-reports
    'events': 1234567890123456789,     # ID #faction-events  
    'leaderboard': 1234567890123456789 # ID #faction-leaderboard
}

ROLES = {
    'admin': 1234567890123456789,      # Role admin para !resetweek
    'farm_king': 1234567890123456789   # Role PREMIUM semanal
}

WEEK_RESET_DAY = 0  # 0=Domingo
