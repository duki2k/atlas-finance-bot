# config.py — Atlas Radar Pro (SPOT-only)

# Canal onde comandos podem ser executados (admin-bot)
CANAL_ADMIN = 1467296892256911493  # <- ID do canal admin-bot

# Canais (restrinja por cargo no Discord: permissões do canal)
CANAL_MEMBRO = 1468294566024052800       # <- canal somente cargo MEMBRO (4h)
CANAL_INVESTIDOR = 1468861013138079859   # <- canal somente cargo INVESTIDOR (1m/5m/15m)
CANAL_LOGS = 1467579765274837064         # opcional

# Opcional: pingar cargos nas mensagens (0 = não pingar)
ROLE_MEMBRO_ID = 1467902779447316512
ROLE_INVESTIDOR_ID = 1467782321095577821

# Telegram
TELEGRAM_ENABLED = True
# ENV: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID

# Liga/desliga motores
RADAR_ENABLED = True

# Watchlists
WATCHLIST_MEMBRO = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WATCHLIST_INVESTIDOR = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# Frequências
SCAN_SECONDS = 10  # loop interno (não é alerta). Alertas disparam por “slot” de candle.

# Regras por timeframe
RULES = {
    "1m":  {"lookback": 30, "vol_mult": 1.20, "atr_period": 14},
    "5m":  {"lookback": 24, "vol_mult": 1.25, "atr_period": 14},
    "15m": {"lookback": 20, "vol_mult": 1.30, "atr_period": 14},
    "4h":  {"lookback": 20, "vol_mult": 1.10, "atr_period": 14},
}

EMA_FAST = 9
EMA_SLOW = 21

# Anti-spam
MAX_ALERTS_PER_CYCLE = {
    "investidor": 6,
    "membro": 3,
}

COOLDOWN_MINUTES = {
    # investidor
    ("investidor", "1m",  "SPIKE"): 10,
    ("investidor", "1m",  "BREAK"): 20,
    ("investidor", "1m",  "EMA"):   45,

    ("investidor", "5m",  "SPIKE"): 20,
    ("investidor", "5m",  "BREAK"): 45,
    ("investidor", "5m",  "EMA"):   60,

    ("investidor", "15m", "SPIKE"): 45,
    ("investidor", "15m", "BREAK"): 90,
    ("investidor", "15m", "EMA"):   120,

    # membro (4h)
    ("membro", "4h", "BREAK"): 360,
    ("membro", "4h", "EMA"):   360,
}

# Trigger de “spike” (educacional)
SPIKE_PCT = {
    "1m": 0.35,   # mudança rápida (últimos 5 minutos via 1m closes)
    "5m": 0.80,   # último candle 5m
    "15m": 1.20,  # último candle 15m
}

# Slots de envio “membro” (4h) — minuto fixo pra ficar bonito
MEMBRO_MINUTE = 5  # envia em 00:05, 04:05, 08:05, ...
