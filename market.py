import requests
import time

# ─────────────────────────────
# MAPAS
# ─────────────────────────────

CRYPTO_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "USDT-USD": "tether",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "SOL-USD": "solana"
}

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ─────────────────────────────
# CRIPTO (CoinGecko)
# ─────────────────────────────

def _preco_crypto(ativo):
    coin_id = CRYPTO_MAP.get(ativo)
    if not coin_id:
        raise ValueError("Cripto não mapeada")

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}

    r = requests.get(url, params=params, timeout=10).json()
    return float(r[coin_id]["usd"])

# ─────────────────────────────
# AÇÕES (Yahoo Chart API)
# ─────────────────────────────

def _preco_acao(ativo):
    url = YAHOO_CHART_URL.format(ativo)
    params = {
        "range": "1d",
        "interval": "1d"
    }

    r = requests.get(url, headers=HEADERS, params=params, timeout=10).json()

    try:
        result = r["chart"]["result"][0]
        close = result["indicators"]["quote"][0]["close"][-1]
        return float(close)
    except Exception:
        raise ValueError("Sem dados da ação")

# ─────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────

def preco_atual(ativo):
    if ativo.endswith("-USD"):
        return _preco_crypto(ativo)
    return _preco_acao(ativo)

