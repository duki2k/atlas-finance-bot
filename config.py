# ============================
# ATLAS BOT v6 — CONFIG FINAL
# ============================

from __future__ import annotations

import re
from typing import List, Tuple


# ─────────────────────────────
# ✅ Canais (IDs do Discord)
# ─────────────────────────────
CANAL_ADMIN = 1467296892256911493

CANAL_LOGS = 1467579765274837064
CANAL_LOGS_SINAIS = 1469445445460693102  # opcional

CANAL_NEWS_MEMBRO = 1466255506657251469
CANAL_NEWS_INVESTIDOR = 1469445663983931503

CANAL_BINANCE_MEMBRO = 1468861013138079859
CANAL_BINANCE_INVESTIDOR = 1468294566024052800

CANAL_BINOMO_MEMBRO = 1468877305651921090
CANAL_BINOMO_INVESTIDOR = 1468877360697839688


# ─────────────────────────────
# ✅ Cargos (IDs) — coloque se quiser pingar
# (se não quiser ping, deixe 0)
# ─────────────────────────────
ROLE_MEMBRO_ID = 1467902779447316512
ROLE_INVESTIDOR_ID = 1467782321095577821


# ─────────────────────────────
# 🔗 Links / CTAs (sem “indicação”)
# ─────────────────────────────
DISCORD_INVITE_LINK = "https://discord.gg/NJ5EB97B"

BINANCE_REF_LINK = "https://www.binance.com/activity/referral-entry/CPA?ref=CPA_00V7RUKGMN"
BINOMO_REF_LINK = "https://binomo-invitefriend.com/auth?invite_code=cdb1ad8837e4ffa1bf771e28824f5e0c#SignUp"


# ─────────────────────────────
# 📰 NEWS (PT/EN) — fontes RSS (EN base)
# IMPORTANTE: formato é LISTA DE TUPLAS (fonte, url)
# ─────────────────────────────
NEWS_RSS_FEEDS_EN: List[Tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("The Defiant", "https://thedefiant.io/feed/"),
]

# Loop de notícias (a cada X minutos)
NEWS_EVERY_MINUTES = 30

# Limites por tier (Discord)
NEWS_MAX_ITEMS_MEMBER = 4
NEWS_MAX_ITEMS_INVEST = 7


# ─────────────────────────────
# 💠 BINANCE (Mentor / Investimento) — sem entradas
# ─────────────────────────────
BINANCE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT", "DOGEUSDT",
    "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "TONUSDT",
]

# Membro: 1 recomendação a cada 2 dias (horário fixo)
BINANCE_MEMBER_TIMES = ["09:00"]
BINANCE_MEMBER_EVERY_DAYS = 2

# Premium: 2 por dia
BINANCE_INVEST_TIMES = ["09:00", "18:00"]

# Regras de qualidade do mentor
BINANCE_MIN_DROP_24H = 2.0   # precisa ter caído pelo menos 2% em 24h (em 1h candles)
BINANCE_MIN_SCORE = 70.0     # score mínimo pra virar "pick"


# ─────────────────────────────
# 🎯 BINOMO (Trading) — qualidade > quantidade
# ─────────────────────────────
BINOMO_TICKERS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X",
    "USDCHF=X", "NZDUSD=X", "EURJPY=X", "EURGBP=X", "XAUUSD=X",
    "XAGUSD=X", "CL=F", "BZ=F", "^GSPC", "^NDX",
]

# Membro: 1 entrada por dia em M5
TRADING_MEMBER_TIMES = ["12:00"]

# Premium: 1/h no minuto 00, até 3 entradas (M5 + M15)
TRADING_INVEST_ON_MINUTE = 0
TRADING_INVEST_MAX_PER_HOUR = 3
TRADING_INVEST_TFS = ["5m", "15m"]

# Cooldown por ticker (premium)
TRADING_TICKER_COOLDOWN_MINUTES_INVEST = 180  # 3h

# Qualidade do trading (thresholds)
TRADING_SPIKE_1M = 0.25
TRADING_SPIKE_5M = 0.60
TRADING_SPIKE_15M = 1.00
TRADING_MIN_SCORE = 70.0
TRADING_EMA_FAST = 9
TRADING_EMA_SLOW = 21


# ─────────────────────────────
# ✅ Validação (pra parar dor de cabeça no deploy)
# ─────────────────────────────
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def validate_config() -> List[str]:
    """
    Retorna lista de problemas. Vazio = OK.
    O main.py deve chamar isso no boot e logar.
    """
    problems: List[str] = []

    # ids obrigatórios
    required_ints = {
        "CANAL_ADMIN": CANAL_ADMIN,
        "CANAL_LOGS": CANAL_LOGS,
        "CANAL_NEWS_MEMBRO": CANAL_NEWS_MEMBRO,
        "CANAL_NEWS_INVESTIDOR": CANAL_NEWS_INVESTIDOR,
        "CANAL_BINANCE_MEMBRO": CANAL_BINANCE_MEMBRO,
        "CANAL_BINANCE_INVESTIDOR": CANAL_BINANCE_INVESTIDOR,
        "CANAL_BINOMO_MEMBRO": CANAL_BINOMO_MEMBRO,
        "CANAL_BINOMO_INVESTIDOR": CANAL_BINOMO_INVESTIDOR,
    }
    for k, v in required_ints.items():
        if not isinstance(v, int) or v <= 0:
            problems.append(f"{k} inválido (precisa ser int > 0).")

    # horários
    for name, arr in [
        ("BINANCE_MEMBER_TIMES", BINANCE_MEMBER_TIMES),
        ("BINANCE_INVEST_TIMES", BINANCE_INVEST_TIMES),
        ("TRADING_MEMBER_TIMES", TRADING_MEMBER_TIMES),
    ]:
        if not isinstance(arr, list) or not arr:
            problems.append(f"{name} vazio.")
            continue
        bad = [x for x in arr if not isinstance(x, str) or not _TIME_RE.match(x.strip())]
        if bad:
            problems.append(f"{name} contém horário inválido: {bad} (use 'HH:MM').")

    # feeds (tuplas)
    if not NEWS_RSS_FEEDS_EN:
        problems.append("NEWS_RSS_FEEDS_EN vazio.")
    else:
        for it in NEWS_RSS_FEEDS_EN:
            if not (isinstance(it, (tuple, list)) and len(it) == 2 and all(isinstance(x, str) and x.strip() for x in it)):
                problems.append(f"NEWS_RSS_FEEDS_EN item inválido: {it} (use ('Fonte','URL')).")

    # listas de símbolos/tickers
    if not BINANCE_SYMBOLS or len(BINANCE_SYMBOLS) < 5:
        problems.append("BINANCE_SYMBOLS vazio/curto demais.")
    if not BINOMO_TICKERS or len(BINOMO_TICKERS) < 5:
        problems.append("BINOMO_TICKERS vazio/curto demais.")

    # trading tfs
    ok_tfs = {"1m", "5m", "15m", "1h", "4h"}
    if not TRADING_INVEST_TFS or any(tf not in ok_tfs for tf in TRADING_INVEST_TFS):
        problems.append(f"TRADING_INVEST_TFS inválido. Use apenas: {sorted(ok_tfs)}")

    # sanity
    if BINANCE_MEMBER_EVERY_DAYS < 1:
        problems.append("BINANCE_MEMBER_EVERY_DAYS precisa ser >= 1")
    if NEWS_EVERY_MINUTES < 5:
        problems.append("NEWS_EVERY_MINUTES muito baixo (>= 5 recomendado).")

    return problems
