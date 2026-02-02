import requests

CRYPTO_MAP = {
    "BTC-USD":"bitcoin","ETH-USD":"ethereum","SOL-USD":"solana",
    "BNB-USD":"binancecoin","XRP-USD":"ripple","ADA-USD":"cardano",
    "AVAX-USD":"avalanche-2","DOT-USD":"polkadot",
    "LINK-USD":"chainlink","MATIC-USD":"matic-network"
}

def dados_crypto(ativo):
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
    return r[coin]["usd"], r[coin]["usd_24h_change"]


def dados_acao(ativo):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ativo}"
    params = {"range": "1d", "interval": "1d"}

    r = requests.get(url, params=params, timeout=10).json()
    try:
        q = r["chart"]["result"][0]["indicators"]["quote"][0]
        open_ = q["open"][0]
        close = q["close"][0]
        var = ((close - open_) / open_) * 100
        return close, var
    except:
        return None, None


def dados_ativo(ativo):
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)
    return dados_acao(ativo)
