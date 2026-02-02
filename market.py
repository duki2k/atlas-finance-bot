import requests
import time

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─────────────────────────────
# CRIPTO — CoinGecko (lote + cache)
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
    "MATIC-USD": "polygon-pos",
}

_crypto_cache = {}
_crypto_cache_time = 0

# ─────────────────────────────
# CACHE GERAL (último valor válido)
# ─────────────────────────────

_last_good = {}  # {ativo: (preco, variacao, timestamp)}

def _store_cache(ativo, preco, variacao):
    if preco is None or variacao is None:
        return
    _last_good[ativo] = (float(preco), float(variacao), time.time())

def _get_cache(ativo, max_age=60 * 60 * 24):
    item = _last_good.get(ativo)
    if not item:
        return None, None
    preco, variacao, ts = item
    if time.time() - ts > max_age:
        return None, None
    return preco, variacao

# ─────────────────────────────
# HELPERS
# ─────────────────────────────

def eh_fii(ativo):
    return ativo.endswith("11.SA")

def _http_get_json(url, params=None, headers=None, timeout=12, retries=2):
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            return r.json()
        except Exception:
            time.sleep(0.3 * (i + 1))
    return {}

def _last_two_valid(nums):
    vals = []
    for x in reversed(nums or []):
        if x is None:
            continue
        try:
            fx = float(x)
        except:
            continue
        if fx != fx:
            continue
        vals.append(fx)
        if len(vals) == 2:
            return vals[0], vals[1]
    return None, None

def _pct_change(last, prev):
    if last is None or prev is None or prev == 0:
        return None
    return ((last - prev) / prev) * 100.0

# ─────────────────────────────
# CRIPTOS
# ─────────────────────────────

def _atualizar_cache_crypto():
    global _crypto_cache, _crypto_cache_time

    ids = ",".join(CRYPTO_MAP.values())
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }

    data = _http_get_json(url, params=params, timeout=15, retries=2)
    if isinstance(data, dict) and data:
        _crypto_cache = data
        _crypto_cache_time = time.time()

def dados_crypto(ativo):
    coin = CRYPTO_MAP.get(ativo)
    if not coin:
        return None, None

    if time.time() - _crypto_cache_time > 60:
        _atualizar_cache_crypto()

    d = _crypto_cache.get(coin)
    if not d:
        return _get_cache(ativo)

    p = d.get("usd")
    ch = d.get("usd_24h_change")
    if p is None or ch is None:
        return _get_cache(ativo)

    _store_cache(ativo, p, ch)
    return float(p), float(ch)

# ─────────────────────────────
# AÇÕES / ETFs — YAHOO QUOTE (primária)
# ─────────────────────────────

def dados_acao_yahoo_quote(ativo):
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": ativo}

    j = _http_get_json(url, params=params, headers=HEADERS, timeout=12, retries=2)
    res = j.get("quoteResponse", {}).get("result", [])

    if not res:
        return None, None

    q = res[0]
    price = q.get("regularMarketPrice")
    prev = q.get("regularMarketPreviousClose")

    if price is None or prev is None:
        return None, None

    var = _pct_change(float(price), float(prev))
    if var is None:
        return None, None

    return float(price), float(var)

# ─────────────────────────────
# AÇÕES / ETFs — YAHOO CHART (secundária)
# ─────────────────────────────

def dados_acao_yahoo_chart(ativo):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ativo}"
    params = {"range": "5d", "interval": "1d"}

    r = _http_get_json(url, params=params, headers=HEADERS, timeout=12, retries=2)
    result = r.get("chart", {}).get("result")

    if not result:
        return None, None

    quote = result[0].get("indicators", {}).get("quote", [{}])[0]
    closes = quote.get("close", [])

    last, prev = _last_two_valid(closes)
    var = _pct_change(last, prev)

    if last is None or var is None:
        return None, None

    return float(last), float(var)

# ─────────────────────────────
# STOOQ (fallback)
# ─────────────────────────────

def dados_acao_stooq(ativo):
    s = ativo.lower()

    if s.endswith(".sa"):
        s = s.replace(".sa", ".br")
    elif not s.endswith(".us"):
        s += ".us"

    url = f"https://stooq.com/q/l/?s={s}&f=sd2t2ohlcv&h&e=json"
    j = _http_get_json(url, timeout=12, retries=2)

    data = j.get("data")
    if not data:
        return None, None

    d = data[0]
    try:
        close = float(d.get("close"))
        open_ = float(d.get("open"))
    except:
        return None, None

    if open_ <= 0 or close <= 0:
        return None, None

    var = ((close - open_) / open_) * 100.0
    return float(close), float(var)

# ─────────────────────────────
# FUNÇÃO PRINCIPAL (FINAL)
# ─────────────────────────────

def dados_ativo(ativo):
    # 1️⃣ Criptos
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # 2️⃣ Yahoo Quote
    p, v = dados_acao_yahoo_quote(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 3️⃣ Yahoo Chart
    p, v = dados_acao_yahoo_chart(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 4️⃣ Stooq
    time.sleep(0.2)
    p, v = dados_acao_stooq(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 5️⃣ Último valor válido (cache)
    p, v = _get_cache(ativo)
    if p is not None and v is not None:
        return p, v

    # 6️⃣ FII fora do pregão → ignora silenciosamente
    if eh_fii(ativo):
        return None, 0.0

    # Falha real
    return None, None
