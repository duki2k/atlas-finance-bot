import os

# config.py

CANAL_ADMIN = 1467296892256911493
CANAL_ANALISE = 1466255506657251469
CANAL_NOTICIAS = 1466895475415191583
CANAL_LOGS = 1467579765274837064

NEWS_ATIVAS = True

# Rompimento (%). Sugestão: 1.0 cripto / 1.5 ações / 2.0 fiis.
# Aqui é geral (simples). Depois dá pra separar por categoria.
LIMITE_ROMPIMENTO_PCT = 2.0

# Portfólio por categoria (edite à vontade)
ATIVOS = {
    "🪙 Criptomoedas": [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
        "ADA-USD", "AVAX-USD", "DOT-USD", "LINK-USD", "MATIC-USD",
    ],
    "🇺🇸 Ações EUA": [
        "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA",
        "META", "TSLA", "BRK-B", "JPM", "V",
    ],
    "🇧🇷 Ações Brasil": [
        "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "BBAS3.SA",
        "WEGE3.SA", "ABEV3.SA", "B3SA3.SA", "RENT3.SA", "SUZB3.SA",
    ],
    "🏢 FIIs Brasil": [
        "HGLG11.SA", "XPML11.SA", "MXRF11.SA", "VISC11.SA", "BCFF11.SA",
        "KNRI11.SA", "RECT11.SA", "HGRE11.SA", "CPTS11.SA", "IRDM11.SA",
    ],
    "📦 ETFs EUA": [
        "SPY", "QQQ", "VOO", "IVV", "VTI",
        "DIA", "IWM", "EFA", "VEA", "VNQ",
    ],
}

# ─────────────────────────────
# Helpers robustos de ENV (não crasham)
# ─────────────────────────────
def env_str(name: str, default: str = "") -> str:
    try:
        v = os.getenv(name)
        return v.strip() if v is not None else default
    except Exception:
        return default

def env_int(name: str, default: int = 0) -> int:
    try:
        v = os.getenv(name)
        if v is None:
            return default
        v = v.strip()
        if not v:
            return default
        return int(v)
    except Exception:
        return default

def env_bool(name: str, default: bool = False) -> bool:
    try:
        v = os.getenv(name)
        if v is None:
            return default
        v = v.strip().lower()
        return v in ("1", "true", "yes", "y", "on")
    except Exception:
        return default

# ─────────────────────────────
# Trading V2 (safe defaults)
# ─────────────────────────────
TRADING_ENABLED = env_bool("TRADING_ENABLED", True)

# se você não setar agora, fica 0 e o bot NÃO tenta postar no canal
TRADING_CHANNEL_ID = env_int("TRADING_CHANNEL_ID", 0)

# se TRADING_CHANNEL_ID = 0, a restrição fica "flexível" (não trava comandos)
TRADING_CHANNEL_ONLY = env_bool("TRADING_CHANNEL_ONLY", True)

# Trading News
TRADING_NEWS_ATIVAS = env_bool("TRADING_NEWS_ATIVAS", False)
TRADING_NEWS_TIMES = env_str("TRADING_NEWS_TIMES", "08:00,14:00,20:00")

# Resumo diário
TRADING_DAILY_SUMMARY_ATIVO = env_bool("TRADING_DAILY_SUMMARY_ATIVO", False)
TRADING_DAILY_SUMMARY_TIME = env_str("TRADING_DAILY_SUMMARY_TIME", "21:00")


