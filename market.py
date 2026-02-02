import requests
import time

# ─────────────────────────────
# MAPA DE CRIPTOMOEDAS
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

# cache simples para evitar múltiplas chamadas
_crypto_cache = {}
_crypto_cache_time = 0


# ─────────────────────────────
# CRIPTOS — COINGECKO (EM LOTE)
# ─────────────────────────────

def atualizar_cache_crypto():
    global _crypto_cache, _crypto_cache_time

    ids = ",".join(CRYPTO_MAP.values())

    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": ids,
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }

        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if not data:
            return

        _crypto_cache = data
        _crypto_cache_time = time.time()

    except Exception:
        pass


def dados_crypto(ativo):
    coin = CRYPTO_MAP.get(ativo)
    if not coin:
        return None, None

    # atualiza cache a cada 60s
    if time.time() - _crypto_cache_time > 60:
        atualizar_cache_crypto()

    dados = _crypto_cache.get(coin)
    if not dados:
        return None, None

    preco = dados.get("usd")
    variacao = dados.get("usd_24h_change")

    if preco is None or variacao is None:
        return None, None

    return float(preco), float(variacao)


# ─────────────────────────────
# AÇÕES — YAHOO (PRIMÁRIA)
# ─────────────────────────────

def dados_acao_yahoo(ativo):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ativo}"
        params = {"range": "1d", "interval": "1d"}

        r = requests.get(url, headers=HEADERS, params=params, timeout=10).json()
        result = r["chart"]["result"]

        if not result:
            return None, None

        q = result[0]["indicators"]["quote"][0]
        open_ = q["open"][0]
        close = q["close"][0]

        if open_ is None or close is None:
            return None, None

        variacao = ((close - open_) / open_) * 100
        return float(close), float(variacao)

    except Exception:
        return None, None


# ─────────────────────────────
# AÇÕES / ETFs — STOOQ (FALLBACK)
# ─────────────────────────────

def dados_acao_stooq(ativo):
    try:
        simbolo = ativo.lower()

        if simbolo.endswith(".sa"):
            simbolo = simbolo.replace(".sa", ".br")
        elif not simbolo.endswith(".us"):
            simbolo += ".us"

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
# FUNÇÃO PRINCIPAL
# ─────────────────────────────

def dados_ativo(ativo):
    # CRIPTOS
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # AÇÕES / ETFs
    preco, var = dados_acao_yahoo(ativo)
    if preco is not None:
        return preco, var

    time.sleep(0.3)
    return dados_acao_stooq(ativo)
