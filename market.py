import requests

# ───── CRIPTOS (CoinGecko) ─────

CRYPTO_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "ADA-USD": "cardano",
    "XRP-USD": "ripple",
    "BNB-USD": "binancecoin"
}

def preco_crypto(ativo):
    coin = CRYPTO_MAP.get(ativo)
    if not coin:
        return None, None

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": coin,
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }

    r = requests.get(url, params=params, timeout=10).json()
    preco = r[coin]["usd"]
    variacao = r[coin]["usd_24h_change"]

    return preco, variacao


# ───── AÇÕES (Yahoo Finance) ─────

def preco_acao(ativo):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ativo}"
    params = {"range": "1d", "interval": "1d"}

    r = requests.get(url, params=params, timeout=10).json()

    try:
        quote = r["chart"]["result"][0]
        close = quote["indicators"]["quote"][0]["close"][0]
        open_ = quote["indicators"]["quote"][0]["open"][0]

        variacao = ((close - open_) / open_) * 100
        return close, variacao
    except:
        return None, None


# ───── FUNÇÃO PRINCIPAL ─────

def dados_ativo(ativo):
    if ativo.endswith("-USD"):
        return preco_crypto(ativo)
    return preco_acao(ativo)
