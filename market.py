# market.py
import requests
import time

HEADERS = {"User-Agent": "Mozilla/5.0"}

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
    # ✅ Correção definitiva
    "MATIC-USD": "polygon-pos",
}

_crypto_cache = {}
_crypto_cache_time = 0

_last_good = {}  # {ativo: (preco, variacao, timestamp)}

def eh_fii(ativo: str) -> bool:
    return ativo.endswith("11.SA")

def _http_get_json(url, *, params=None, headers=None, timeout=12, retries=2):
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            return r.json()
        except Exception:
            time.sleep(0.35 * (i + 1))
    return {}

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

def _last_two_valid(nums):
    vals = []
    for x in reversed(nums or []):
        if x is None:
            continue
        try:
            fx = float(x)
        except:
            continue
        if fx != fx:  # NaN
            continue
        vals.append(fx)
        if len(vals) == 2:
            return vals[0], vals[1]
    return None, None

def _pct_change(last, prev):
    if last is None or prev is None or prev == 0:
        return None
    return ((last - prev) / prev) * 100.0

# ───────────── CRIPTO (lote + cache) ─────────────

def _atualizar_cache_crypto():
    global _crypto_cache, _crypto_cache_time
    ids = ",".join(CRYPTO_MAP.values())
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"}

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
        # fallback unitário (ajuda em momentos de instabilidade)
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": coin, "vs_currencies": "usd", "include_24hr_change": "true"}
            one = _http_get_json(url, params=params, timeout=12, retries=1)
            dd = one.get(coin)
            if dd and dd.get("usd") is not None and dd.get("usd_24h_change") is not None:
                preco = float(dd["usd"])
                variacao = float(dd["usd_24h_change"])
                _store_cache(ativo, preco, variacao)
                return preco, variacao
        except Exception:
            pass

        return _get_cache(ativo)

    p = d.get("usd")
    ch = d.get("usd_24h_change")
    if p is None or ch is None:
        return _get_cache(ativo)

    preco = float(p)
    variacao = float(ch)
    _store_cache(ativo, preco, variacao)
    return preco, variacao

# ───────────── AÇÕES (Yahoo Quote) ─────────────

def dados_acao_yahoo_quote(ativo):
    try:
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

        price = float(price)
        prev = float(prev)
        var = _pct_change(price, prev)
        if var is None:
            return None, None

        return price, float(var)

    except Exception:
        return None, None

# ───────────── AÇÕES (Yahoo Chart) ─────────────

def dados_acao_yahoo_chart(ativo):
    try:
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
    except Exception:
        return None, None

# ───────────── STOOQ fallback ─────────────

def dados_acao_stooq(ativo):
    try:
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
        close = d.get("close")
        open_ = d.get("open")

        close = float(close)
        open_ = float(open_)
        if open_ <= 0 or close <= 0:
            return None, None

        var = ((close - open_) / open_) * 100.0
        return float(close), float(var)
    except Exception:
        return None, None

# ───────────── FUNÇÃO PRINCIPAL ─────────────

def dados_ativo(ativo):
    # Cripto
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # Yahoo Quote
    p, v = dados_acao_yahoo_quote(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # Yahoo Chart
    p, v = dados_acao_yahoo_chart(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # Stooq
    time.sleep(0.2)
    p, v = dados_acao_stooq(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # Cache final
    p, v = _get_cache(ativo)
    if p is not None and v is not None:
        return p, v

    # FII: pode ficar sem fonte — retornamos neutro sem travar
    if eh_fii(ativo):
        return None, 0.0

    return None, None
