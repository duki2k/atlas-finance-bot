import requests
import time

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─────────────────────────────
# CRIPTO (CoinGecko em LOTE + cache)
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

_crypto_cache = {}
_crypto_cache_time = 0

def _http_get_json(url, *, params=None, headers=None, timeout=12, retries=2, sleep_base=0.4):
    last_exc = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            # alguns bloqueios “silenciosos” retornam html; isso protege:
            return r.json()
        except Exception as e:
            last_exc = e
            time.sleep(sleep_base * (i + 1))
    raise last_exc

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
        return None, None

    p = d.get("usd")
    ch = d.get("usd_24h_change")
    if p is None or ch is None:
        return None, None

    return float(p), float(ch)

# ─────────────────────────────
# Helpers para pegar últimos fechamentos válidos
# ─────────────────────────────

def _last_two_valid(nums):
    """Retorna (ultimo, anterior) ignorando None/NaN."""
    vals = []
    for x in reversed(nums or []):
        if x is None:
            continue
        try:
            fx = float(x)
        except:
            continue
        # evita NaN
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
# Yahoo Finance (melhorado)
# ─────────────────────────────

def dados_acao_yahoo(ativo):
    """
    Usa range 5d e calcula variação por últimos 2 fechamentos válidos,
    o que funciona melhor fora do pregão e para .SA/FIIs.
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
# Stooq (fallback)
# ─────────────────────────────

def dados_acao_stooq(ativo):
    """
    Fallback bom para EUA/ETFs e alguns BR. Para BR: .SA -> .br
    """
    try:
        s = ativo.lower()

        if s.endswith(".sa"):
            s = s.replace(".sa", ".br")
        elif not s.endswith(".us"):
            s = s + ".us"

        url = f"https://stooq.com/q/l/?s={s}&f=sd2t2ohlcv&h&e=json"
        j = _http_get_json(url, timeout=12, retries=2)

        data = j.get("data")
        if not data:
            return None, None

        d = data[0]
        close = d.get("close")
        open_ = d.get("open")

        # Se o stooq não tiver open/close bons, sem dados
        try:
            close = float(close)
            open_ = float(open_)
        except:
            return None, None

        if open_ <= 0 or close <= 0:
            return None, None

        var = ((close - open_) / open_) * 100.0
        return close, var

    except Exception:
        return None, None

# ─────────────────────────────
# Função principal com fallback
# ─────────────────────────────

def dados_ativo(ativo):
    # Cripto
    if ativo.endswith("-USD"):
        return dados_crypto(ativo)

    # Yahoo
    p, v = dados_acao_yahoo(ativo)
    if p is not None and v is not None:
        return p, v

    # fallback Stooq
    time.sleep(0.25)
    return dados_acao_stooq(ativo)
