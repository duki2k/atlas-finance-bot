# signals.py
import time
import math
import requests

HEADERS = {"User-Agent": "AtlasFinanceBot/1.0"}

# Cooldown interno: (exchange, market, symbol, kind, side) -> last_ts
_COOLDOWN = {}

# --------- utils http ---------
def _get_json(url, params=None, timeout=12, retries=2):
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.35 * (i + 1))
    return {"_error": str(last_err) if last_err else "unknown"}

def _float(x):
    try:
        f = float(x)
        if f != f:
            return None
        return f
    except Exception:
        return None

# --------- indicators ---------
def ema(values, period):
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def rsi(values, period=14):
    if not values or len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        if d >= 0:
            gains += d
        else:
            losses += abs(d)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _avg(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)

def _cooldown_ok(key, cooldown_minutes):
    now = time.time()
    last = _COOLDOWN.get(key)
    if last and (now - last) < (cooldown_minutes * 60):
        return False
    _COOLDOWN[key] = now
    return True

# --------- fetch klines ---------
def _parse_binance_klines(rows):
    # row: [open_time, open, high, low, close, volume, ...]
    closes, highs, lows, vols = [], [], [], []
    for row in rows or []:
        c = _float(row[4])
        h = _float(row[2])
        l = _float(row[3])
        v = _float(row[5])
        if c is None or h is None or l is None or v is None:
            continue
        closes.append(c)
        highs.append(h)
        lows.append(l)
        vols.append(v)
    return closes, highs, lows, vols

def fetch_binance_spot(symbol, interval="15m", limit=120):
    # tenta data-api primeiro (menos bloqueios), depois api principal
    urls = [
        "https://data-api.binance.vision/api/v3/klines",
        "https://api.binance.com/api/v3/klines",
    ]
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for url in urls:
        j = _get_json(url, params=params, timeout=12, retries=1)
        if isinstance(j, list) and j:
            return _parse_binance_klines(j)
    return [], [], [], []

def fetch_binance_futures(symbol, interval="15m", limit=120):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    j = _get_json(url, params=params, timeout=12, retries=2)
    if isinstance(j, list) and j:
        return _parse_binance_klines(j)
    return [], [], [], []

def fetch_binance_funding(symbol):
    # premiumIndex traz lastFundingRate (string)
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": symbol}
    j = _get_json(url, params=params, timeout=10, retries=1)
    if isinstance(j, dict):
        fr = _float(j.get("lastFundingRate"))
        return fr  # ex: 0.0001 (0.01%)
    return None

def fetch_mexc_spot(symbol, interval="15m", limit=120):
    # Spot V3: /api/v3/klines (muito similar ao Binance)
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    j = _get_json(url, params=params, timeout=12, retries=2)
    if isinstance(j, list) and j:
        return _parse_binance_klines(j)
    return [], [], [], []

def _mexc_contract_symbol(symbol):
    # BTCUSDT -> BTC_USDT
    if symbol.endswith("USDT") and "_" not in symbol:
        base = symbol.replace("USDT", "")
        return f"{base}_USDT"
    return symbol

def _mexc_interval(interval):
    # MEXC futures usa Min15, Hour4 etc
    m = {
        "1m": "Min1",
        "5m": "Min5",
        "15m": "Min15",
        "30m": "Min30",
        "1h": "Min60",
        "4h": "Hour4",
        "8h": "Hour8",
        "1d": "Day1",
        "1w": "Week1",
        "1M": "Month1",
    }
    return m.get(interval, "Min15")

def fetch_mexc_futures(symbol, interval="15m", limit=120):
    # Futures Market: /api/v1/contract/kline/{symbol}?interval=Min15&start=...&end=...
    # docs usam contract.mexc.com; em alguns ambientes api.mexc.com também funciona.
    bases = [
        "https://contract.mexc.com",
        "https://api.mexc.com",
    ]
    sym = _mexc_contract_symbol(symbol)
    itv = _mexc_interval(interval)

    # range por tempo (segundos)
    now = int(time.time())
    # 15m -> 900s, 5m -> 300s etc (aprox)
    step = 900 if interval == "15m" else 300 if interval == "5m" else 3600 if interval == "1h" else 900
    start = now - (limit * step)
    end = now

    for base in bases:
        url = f"{base}/api/v1/contract/kline/{sym}"
        params = {"interval": itv, "start": start, "end": end}
        j = _get_json(url, params=params, timeout=12, retries=2)
        data = (j or {}).get("data")
        if isinstance(data, dict) and data.get("close"):
            closes = [_float(x) for x in data.get("close", [])]
            highs  = [_float(x) for x in data.get("high", [])]
            lows   = [_float(x) for x in data.get("low", [])]
            vols   = [_float(x) for x in data.get("vol", [])]
            closes = [x for x in closes if x is not None]
            highs  = [x for x in highs if x is not None]
            lows   = [x for x in lows if x is not None]
            vols   = [x for x in vols if x is not None]
            return closes, highs, lows, vols

    return [], [], [], []

def fetch_mexc_funding(symbol):
    bases = [
        "https://contract.mexc.com",
        "https://api.mexc.com",
    ]
    sym = _mexc_contract_symbol(symbol)
    for base in bases:
        url = f"{base}/api/v1/contract/funding_rate/{sym}"
        j = _get_json(url, timeout=10, retries=1)
        data = (j or {}).get("data")
        if isinstance(data, dict):
            fr = _float(data.get("fundingRate"))
            return fr
    return None

# --------- signal logic ---------
def detect_signals(closes, highs, lows, vols):
    """
    Retorna lista de sinais (cada um dict).
    Regras simples (15m):
    - EMA9 x EMA21 (cross)
    - Breakout de 20 candles com volume acima da média
    - RSI extremo (alerta)
    """
    out = []
    if not closes or len(closes) < 30:
        return out

    c_now = closes[-1]
    fast_now = ema(closes[-60:], 9)
    slow_now = ema(closes[-60:], 21)

    # prev para cross
    fast_prev = ema(closes[-61:-1], 9) if len(closes) >= 61 else None
    slow_prev = ema(closes[-61:-1], 21) if len(closes) >= 61 else None

    r = rsi(closes[-30:], 14)
    vol_now = vols[-1] if vols else None
    vol_avg = _avg(vols[-21:-1]) if vols and len(vols) >= 21 else None
    vol_mult = (vol_now / vol_avg) if (vol_now and vol_avg and vol_avg > 0) else None

    # EMA cross
    if fast_prev is not None and slow_prev is not None and fast_now is not None and slow_now is not None:
        if fast_prev <= slow_prev and fast_now > slow_now:
            out.append({
                "kind": "EMA_CROSS",
                "side": "LONG",
                "price": c_now,
                "rsi": r,
                "vol_mult": vol_mult,
                "note": "EMA9 cruzou acima da EMA21",
            })
        elif fast_prev >= slow_prev and fast_now < slow_now:
            out.append({
                "kind": "EMA_CROSS",
                "side": "SHORT",
                "price": c_now,
                "rsi": r,
                "vol_mult": vol_mult,
                "note": "EMA9 cruzou abaixo da EMA21",
            })

    # Breakout 20
    if highs and len(highs) >= 25:
        topo_20 = max(highs[-21:-1])
        if c_now > topo_20 and (vol_mult is None or vol_mult >= 1.4):
            out.append({
                "kind": "BREAKOUT",
                "side": "LONG",
                "price": c_now,
                "rsi": r,
                "vol_mult": vol_mult,
                "note": "Rompimento do topo (20 candles) + volume",
            })

    # RSI extremo (alerta)
    if r is not None:
        if r <= 25:
            out.append({
                "kind": "RSI_EXTREMO",
                "side": "WATCH_LONG",
                "price": c_now,
                "rsi": r,
                "vol_mult": vol_mult,
                "note": "RSI muito baixo (possível exaustão de venda)",
            })
        elif r >= 75:
            out.append({
                "kind": "RSI_EXTREMO",
                "side": "WATCH_SHORT",
                "price": c_now,
                "rsi": r,
                "vol_mult": vol_mult,
                "note": "RSI muito alto (possível exaustão de compra)",
            })

    return out

def scan_signals(
    symbols,
    interval="15m",
    exchanges=("binance", "mexc"),
    cooldown_minutes=60,
    max_spot=8,
    max_futures=8,
):
    spot_out = []
    fut_out = []
    errors = 0

    for ex in exchanges:
        ex = ex.strip().lower()

        for sym in symbols:
            # ----- SPOT -----
            try:
                if len(spot_out) < max_spot:
                    if ex == "binance":
                        closes, highs, lows, vols = fetch_binance_spot(sym, interval=interval)
                    elif ex == "mexc":
                        closes, highs, lows, vols = fetch_mexc_spot(sym, interval=interval)
                    else:
                        closes, highs, lows, vols = [], [], [], []

                    for s in detect_signals(closes, highs, lows, vols):
                        key = (ex, "spot", sym, s["kind"], s["side"])
                        if _cooldown_ok(key, cooldown_minutes):
                            s.update({"exchange": ex, "market": "spot", "symbol": sym})
                            spot_out.append(s)
                            if len(spot_out) >= max_spot:
                                break
            except Exception:
                errors += 1

            # ----- FUTURES -----
            try:
                if len(fut_out) < max_futures:
                    if ex == "binance":
                        closes, highs, lows, vols = fetch_binance_futures(sym, interval=interval)
                        funding = fetch_binance_funding(sym)
                    elif ex == "mexc":
                        closes, highs, lows, vols = fetch_mexc_futures(sym, interval=interval)
                        funding = fetch_mexc_funding(sym)
                    else:
                        closes, highs, lows, vols = [], [], [], []
                        funding = None

                    for s in detect_signals(closes, highs, lows, vols):
                        key = (ex, "futures", sym, s["kind"], s["side"])
                        if _cooldown_ok(key, cooldown_minutes):
                            s.update({"exchange": ex, "market": "futures", "symbol": sym, "funding": funding})
                            fut_out.append(s)
                            if len(fut_out) >= max_futures:
                                break
            except Exception:
                errors += 1

            # micro-pausa pra reduzir chance de rate-limit
            time.sleep(0.15)

    return {"spot": spot_out, "futures": fut_out, "errors": errors}

