# ─────────────────────────────
# Parcerias / Links
# ─────────────────────────────
BINANCE_REF_LINK = "https://www.binance.com/activity/referral-entry/CPA?ref=CPA_00V7RUKGMN"
BINOMO_REF_LINK = "https://binomo-invitefriend.com/auth?invite_code=cdb1ad8837e4ffa1bf771e28824f5e0c#SignUp"

# ─────────────────────────────
# Binance = Mentor (INVESTIMENTO) — sem entradas
# ─────────────────────────────
BINANCE_SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOGEUSDT",
    "DOTUSDT","LTCUSDT","TRXUSDT","ATOMUSDT","TONUSDT",
]

# Membro: 1 recomendação a cada 2 dias (em um horário fixo)
BINANCE_MEMBER_TIMES = ["09:00"]
BINANCE_MEMBER_EVERY_DAYS = 2

# Premium: 2 por dia
BINANCE_INVEST_TIMES = ["09:00", "18:00"]

# ─────────────────────────────
# Binomo = Trading (ENTRADAS)
# ─────────────────────────────
# Observação: usamos Yahoo (dados públicos) para gerar entradas educacionais.
BINOMO_TICKERS = [
    "EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X",
    "USDCHF=X","NZDUSD=X","EURJPY=X","EURGBP=X","XAUUSD=X",
    "XAGUSD=X","CL=F","BZ=F","^GSPC","^NDX",
]

# Membro: 1 entrada por dia em M5
TRADING_MEMBER_TIMES = ["12:00"]   # pode mudar depois se quiser

# Premium: a cada 1 hora, 3 entradas (M5 + M15)
TRADING_INVEST_ON_MINUTE = 0       # minuto do relógio (00)
TRADING_INVEST_MAX_PER_HOUR = 3
TRADING_INVEST_TFS = ["5m", "15m"]
