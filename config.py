# config.py — Atlas Radar v4 (parcerias + canais por cargo)

# ── LINKS (PREENCHA)
BINANCE_REF_LINK = "https://www.binance.com/referral/earn-together/refer2earn-usdc/claim?hl=pt-BR&ref=GRO_28502_8H34D&utm_source=default"
BINOMO_REF_LINK  = "https://binomo-invitefriend.com/auth?invite_code=cdb1ad8837e4ffa1bf771e28824f5e0c#SignUp"
DISCORD_INVITE_LINK = "https://discord.gg/NJ5EB97B"

# ── CANAL ADMIN (onde pode usar comandos)
CANAL_ADMIN = 1467296892256911493  # ID do canal admin-bot

# ── CANAIS BINANCE (SPOT/CRIPTO)
CANAL_BINANCE_MEMBRO = 1468294566024052800       # canal só cargo MEMBRO
CANAL_BINANCE_INVESTIDOR = 1468861013138079859   # canal só cargo INVESTIDOR

# ── CANAIS BINOMO (ENTRADAS 1m/5m/15m)
CANAL_BINOMO_MEMBRO = 1468877305651921090        # canal só cargo MEMBRO
CANAL_BINOMO_INVESTIDOR = 1468877360697839688    # canal só cargo INVESTIDOR

# ── CANAL NEWSLETTER / ALERTAS CRIPTO
CANAL_NEWS_CRIPTO = 1466255506657251469

# ── LOGS
CANAL_LOGS = 1467579765274837064

# ── CARGOS (opcional ping)
ROLE_MEMBRO_ID = 1467902779447316512
ROLE_INVESTIDOR_ID = 1467782321095577821

# ── TELEGRAM
TELEGRAM_ENABLED = True
TELEGRAM_SEND_BINANCE = True
TELEGRAM_SEND_BINOMO  = False   # investidor pode virar spam — recomendo False
TELEGRAM_SEND_NEWS    = True
# ENV: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID

# ── HORÁRIOS MEMBRO (4 por dia)
# (BRT) 09:00 / 13:00 / 17:00 / 21:00
MEMBRO_TIMES = ["09:00", "13:00", "17:00", "21:00"]

# ── INVESTIDOR: 5 por hora (a cada 12 min)
INVESTIDOR_EVERY_MINUTES = 12

# ── WATCHLIST BINANCE (15 cripto “potencial / liquidez”)
BINANCE_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","ARBUSDT",
    "OPUSDT","INJUSDT","RNDRUSDT","SUIUSDT","MATICUSDT",
]

# ── ATIVOS “BINOMO” (15 instrumentos via Yahoo Chart)
# (Você opera na plataforma, o bot só usa dados públicos pra gerar leitura)
BINOMO_TICKERS = [
    "EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X",
    "USDCHF=X","NZDUSD=X","EURJPY=X","GBPJPY=X","XAUUSD=X",
    "CL=F","GC=F","SI=F","^GSPC","^IXIC",
]

# ── REGRAS BINANCE (dips = chance de compra spot)
# thresholds em % para considerar “queda”
BINANCE_DIP_15M = -0.35
BINANCE_DIP_1H  = -0.90
BINANCE_TOP_N   = 3

# ── REGRAS BINOMO (setup simples e consistente)
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_BUY_BELOW = 30
RSI_SELL_ABOVE = 70

# ── NEWSLETTER (fontes RSS)
NEWS_RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("The Defiant", "https://thedefiant.io/feed/"),
]
NEWS_EVERY_MINUTES = 30
NEWS_MAX_ITEMS = 6
