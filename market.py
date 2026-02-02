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
# CACHE GERAL (último valor válido por ativo)
# ─────────────────────────────
_last_good = {}  # { "AAPL": (preco, variacao, timestamp) }


def _http_get_json(url, *, params=None, headers=None, timeout=12, retries=2, sleep_base=0.35):
    last_exc = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            return r.json()
        except Exception as e:
            last_exc = e
            time.sleep(sleep_base * (i + 1))
    raise last_exc


def _store_cache(ativo, preco, variacao):
    # armazena só se for “válido”
    if preco is None or variacao is None:
        return
    _last_good[ativo] = (float(preco), float(variacao), time.time())


def _get_cache(ativo, max_age_sec=60 * 60 * 24):
    """
    Retorna último valor válido se existir e não estiver velho demais.
    Por padrão aceita até 24h (bom para fora do pregão).
    """
    item = _last_good.get(ativo)
    if not item:
        return None, None
    preco, variacao, ts = item
    if (time.time() - ts) > max_age_sec:
        return None, None
    return preco, variacao


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

    try:
        data = _http_get_json(url, params=params, timeout=15, retries=2)
        if isinstance(data, dict) and data:
            _crypto_cache = data
            _crypto_cache_time = time.time()
    except Exception:
        pass


def dados_crypto(ativo):
    coin = CRYPTO_MAP.get(ativo)
    if not coin:
        return None, None

    # refresh a cada 60s
    if time.time() - _crypto_cache_time > 60:
        _atualizar_cache_crypto()

    d = _crypto_cache.get(coin)
    if not d:
        # tenta cache geral como última saída
        return _get_cache(ativo)

    p = d.get("usd")
    ch = d.get("usd_24h_change")

    if p is None or ch is None:
        return _get_cache(ativo)

    preco, variacao = float(p), float(ch)
    _store_cache(ativo, preco, variacao)
    return preco, variacao


# ─────────────────────────────
# HELPERS (últimos fechamentos)
# ─────────────────────────────

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


# ─────────────────────────────
# AÇÕES/ETFs — YAHOO QUOTE (PRIMÁRIA MAIS ESTÁVEL)
# ─────────────────────────────

def dados_acao_yahoo_quote(ativo):
    """
    Usa endpoint v7/finance/quote:
    - regularMarketPrice
    - regularMarketPreviousClose
    Muito mais estável do que o chart para vários tickers.
    """
    try:
        url = "https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": ativo}

        j = _http_get_json(url, params=params, headers=HEADERS, timeout=12, retries=2)

        result = j.get("quoteResponse", {}).get("result", [])
        if not result:
            return None, None

        q = result[0]
        price = q.get("regularMarketPrice")
        prev_close = q.get("regularMarketPreviousClose")

        if price is None or prev_close is None:
            return None, None

        price = float(price)
        prev_close = float(prev_close)

        var = _pct_change(price, prev_close)
        if var is None:
            return None, None

        return price, float(var)

    except Exception:
        return None, None


# ─────────────────────────────
# AÇÕES/ETFs — YAHOO CHART (SECUNDÁRIA)
# ─────────────────────────────

def dados_acao_yahoo_chart(ativo):
    """
    Usa range 5d e calcula variação por últimos 2 fechamentos válidos.
    """
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


# ─────────────────────────────
# STOOQ (FALLBACK)
# ─────────────────────────────

def dados_acao_stooq(ativo):
    try:
        s = ativo.lower()

        # Brasil: .SA -> .BR
        if s.endswith(".sa"):
            s = s.replace(".sa", ".br")
        # Se não tem sufixo, assume US
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

        try:
            close = float(close)
            open_ = float(open_)
        except:
            return None, None

        if open_ <= 0 or close <= 0:
            return None, None

        var = ((close - open_) / open_) * 100.0
        return float(close), float(var)

    except Exception:
        return None, None


# ─────────────────────────────
# FUNÇÃO PRINCIPAL (COM “QUASE ZERO FALHA”)
# ─────────────────────────────

def dados_ativo(ativo):
    # 1) Cripto
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # 2) Yahoo QUOTE (primário)
    p, v = dados_acao_yahoo_quote(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 3) Yahoo CHART (secundário)
    p, v = dados_acao_yahoo_chart(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 4) STOOQ (fallback)
    time.sleep(0.2)
    p, v = dados_acao_stooq(ativo)
    if p is not None and v is not None:
        _store_cache(ativo, p, v)
        return p, v

    # 5) ÚLTIMO VALOR VÁLIDO (cache)
    p, v = _get_cache(ativo)
    if p is not None and v is not None:
        return p, v

    # Falhou tudo
    return None, None
