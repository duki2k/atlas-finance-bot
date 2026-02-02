import requests
import time

# ─────────────────────────────
# MAPA DE CRIPTOMOEDAS (CoinGecko)
# ─────────────────────────────

CRYPTO_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2",
    "DOT-USD": "polkadot",
    "LINK-USD": "chainlink",
    "MATIC-USD": "matic-network",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ─────────────────────────────
# CRIPTOS — CoinGecko (primária)
# ─────────────────────────────

def dados_crypto(ativo):
    coin = CRYPTO_MAP.get(ativo)
    if not coin:
        return None, None

    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin,
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }

        r = requests.get(url, params=params, timeout=10).json()

        preco = r[coin].get("usd")
        variacao = r[coin].get("usd_24h_change")

        if preco is None or variacao is None:
            return None, None

        return float(preco), float(variacao)

    except Exception:
        return None, None


# ─────────────────────────────
# AÇÕES — YAHOO (primária)
# ─────────────────────────────

def dados_acao_yahoo(ativo):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ativo}"
        params = {"range": "1d", "interval": "1d"}

        r = requests.get(url, headers=HEADERS, params=params, timeout=10).json()

        result = r["chart"]["result"]
        if not result:
            return None, None

        quote = result[0]["indicators"]["quote"][0]

        open_ = quote["open"][0]
        close = quote["close"][0]

        if open_ is None or close is None:
            return None, None

        variacao = ((close - open_) / open_) * 100
        return float(close), float(variacao)

    except Exception:
        return None, None


# ─────────────────────────────
# AÇÕES / ETFs — STOOQ (fallback)
# ─────────────────────────────

def dados_acao_stooq(ativo):
    """
    Stooq funciona muito bem como fallback para:
    - Ações EUA
    - ETFs
    - Mercado fora do horário
    """

    try:
        simbolo = ativo.lower()

        # conversão de sufixos
        if simbolo.endswith(".sa"):
            simbolo = simbolo.replace(".sa", ".br")
        elif not simbolo.endswith(".us"):
            simbolo = simbolo + ".us"

        url = f"https://stooq.com/q/l/?s={simbolo}&f=sd2t2ohlcv&h&e=json"
        r = requests.get(url, timeout=10).json()

        dados = r.get("data")
        if not dados:
            return None, None

        d = dados[0]

        open_ = float(d["open"])
        close = float(d["close"])

        if open_ <= 0 or close <= 0:
            return None, None

        variacao = ((close - open_) / open_) * 100
        return close, variacao

    except Exception:
        return None, None


# ─────────────────────────────
# FUNÇÃO PRINCIPAL (COM FALLBACK)
# ─────────────────────────────

def dados_ativo(ativo):
    """
    Ordem de tentativa:
    1️⃣ Cripto → CoinGecko
    2️⃣ Ação/ETF → Yahoo
    3️⃣ Ação/ETF → Stooq (fallback)
    """

    # CRIPTOS
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # AÇÕES / ETFs — Yahoo
    preco, var = dados_acao_yahoo(ativo)
    if preco is not None and var is not None:
        return preco, var

    # fallback — Stooq
    time.sleep(0.3)  # evita bloqueio
    return dados_acao_stooq(ativo)
