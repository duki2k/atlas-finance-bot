# config.py (Atlas Radar v3 - SPOT)
# ✅ Ajuste os IDs abaixo

# Canal onde comandos podem ser executados (admin-bot)
CANAL_ADMIN = 1467296892256911493

# Canais onde o bot publica alertas e pulso
CANAL_ALERTAS = 1466255506657251469  # <- coloque o ID do canal #alertas
CANAL_PULSO   = 1468294566024052800  # <- coloque o ID do canal #pulso (pode ser o mesmo)
CANAL_LOGS    = 1467579765274837064  # opcional

# (Opcional) Ping de cargo em alertas: coloque 0 pra não pingar
ROLE_PING_ID = 0  # ex: 123456789012345678

# Telegram
TELEGRAM_ENABLED = True  # se não tiver token/chat_id, deixa True mesmo (o código falha silencioso)
# Tokens ficam em ENV: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID

# Radar
RADAR_ENABLED = True
SCAN_EVERY_SECONDS = 60  # “alertas o tempo todo” = scaneia a cada 1 minuto

# Watchlist SPOT (Binance symbols)
WATCHLIST = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
]

# ─────────────────────────────
# Regras de alerta (SPOT)
# ─────────────────────────────
# 1) Spike 5m: variação percentual em 5 minutos
SPIKE_5M_DEFAULT_PCT = 0.80  # padrão
SPIKE_5M_PCT = {             # overrides por ativo (opcional)
    "BTCUSDT": 0.60,
    "ETHUSDT": 0.75,
}

# 2) Breakout/Breakdown 15m (rompe máxima/mínima 20 candles) + volume
BREAK_15M_LOOKBACK = 20
BREAK_15M_VOL_MULT = 1.30

# 3) Tendência 15m (EMA9 x EMA21 cross)
EMA_FAST = 9
EMA_SLOW = 21

# Anti-spam
MAX_ALERTS_PER_CYCLE = 5

COOLDOWN_MINUTES = {
    "SPIKE_5M": 10,
    "BREAKOUT_15M": 45,
    "BREAKDOWN_15M": 45,
    "EMA_CROSS_15M": 60,
}

# Pulso (mensagem “profissional” recorrente com o que observar)
PULSE_ENABLED = True
PULSE_TIMES_BRT = ["06:05", "12:05", "18:05", "22:05"]  # horários Brasil
