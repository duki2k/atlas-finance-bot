# ============================
# ATLAS BOT v6 — CONFIG FINAL
# ============================

# ✅ Admin onde comandos podem rodar
CANAL_ADMIN = 1467296892256911493
# Alias (algumas versões usam esse nome)
CANAL_ADMIN_BOT = CANAL_ADMIN

# ✅ Logs
CANAL_LOGS = 1467579765274837064
CANAL_LOGS_SINAIS = 1469445445460693102  # opcional

# ✅ News separada (membro vs investidor)
CANAL_NEWS_MEMBRO = 1466255506657251469
CANAL_NEWS_INVESTIDOR = 1469445663983931503
# Alias (algumas versões antigas só tem 1 canal)
CANAL_NEWS_CRIPTO = CANAL_NEWS_MEMBRO

# ✅ Binance (INVESTIMENTO / Mentor) — sem entradas
CANAL_BINANCE_MEMBRO = 1468861013138079859
CANAL_BINANCE_INVESTIDOR = 1468294566024052800

# ✅ Trading (BINOMO)
CANAL_BINOMO_MEMBRO = 1468877305651921090
CANAL_BINOMO_INVESTIDOR = 1468877360697839688
# Aliases (algumas versões usam "TRADING")
CANAL_TRADING_MEMBRO = CANAL_BINOMO_MEMBRO
CANAL_TRADING_INVESTIDOR = CANAL_BINOMO_INVESTIDOR

# ─────────────────────────────
# Parcerias / Links
# ─────────────────────────────
BINANCE_REF_LINK = "https://www.binance.com/activity/referral-entry/CPA?ref=CPA_00V7RUKGMN"
BINOMO_REF_LINK = "https://binomo-invitefriend.com/auth?invite_code=cdb1ad8837e4ffa1bf771e28824f5e0c#SignUp"

# Para o call-to-action nas news (Telegram/Discord)
DISCORD_INVITE_LINK = "https://discord.gg/NJ5EB97B"

# ─────────────────────────────
# Telegram (news)
# (tokens/chat_id ficam em ENV no Railway; aqui é só liga/desliga)
# ─────────────────────────────
TELEGRAM_ENABLED = True
TELEGRAM_SEND_NEWS = True

# ─────────────────────────────
# NEWS (PT/EN: mesma notícia traduzida)
# Horários (BRT)
# ─────────────────────────────
NEWS_MEMBER_TIMES = ["09:00"]                 # membro 1x/dia
NEWS_INVEST_TIMES = ["09:00", "18:00"]        # investidor 2x/dia
NEWS_MAX_ITEMS_MEMBER = 4
NEWS_MAX_ITEMS_INVEST = 7

# Feeds RSS (EN base; PT você traduz no texto)
# Formato: lista de URLs
NEWS_RSS_FEEDS_EN = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("The Defiant", "https://thedefiant.io/feed/"),
]


# ─────────────────────────────
# Binance = Mentor (INVESTIMENTO) — sem entradas
# ─────────────────────────────
BINANCE_SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","AVAXUSDT","LINKUSDT","MATICUSDT","DOGEUSDT",
    "DOTUSDT","LTCUSDT","TRXUSDT","ATOMUSDT","TONUSDT",
]

# Membro: 1 recomendação a cada 2 dias (horário fixo)
BINANCE_MEMBER_TIMES = ["09:00"]
BINANCE_MEMBER_EVERY_DAYS = 2

# Premium: 2 por dia
BINANCE_INVEST_TIMES = ["09:00", "18:00"]

# ─────────────────────────────
# Binomo = Trading (ENTRADAS)
# ─────────────────────────────
BINOMO_TICKERS = [
    "EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X",
    "USDCHF=X","NZDUSD=X","EURJPY=X","EURGBP=X","XAUUSD=X",
    "XAGUSD=X","CL=F","BZ=F","^GSPC","^NDX",
]

# Membro: 1 entrada diária (M5)
TRADING_MEMBER_TIMES = ["12:00"]

# Premium: a cada 1h, 3 entradas (M5 + M15)
TRADING_INVEST_ON_MINUTE = 0
TRADING_INVEST_MAX_PER_HOUR = 3
TRADING_INVEST_TFS = ["5m", "15m"]

# ✅ Cooldown por ticker (premium)
TRADING_TICKER_COOLDOWN_MINUTES_INVEST = 180
