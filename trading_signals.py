import time
import aiohttp
from typing import List, Dict, Optional, Tuple

_SESSION: Optional[aiohttp.ClientSession] = None

# cooldown: {(symbol, market, interval, kind): last_ts}
_LAST: Dict[Tuple[str, str, str, str], float] = {}

def set_session(session: aiohttp.ClientSession):
    global _SESSION
    _SESSION = session

# ─────────────────────────────
# Binance endpoints (free)
# ─────────────────────────────
SPOT = "https://api.binance.com/api/v3/klines"
FUTURES = "https://fapi.binance.com/fapi/v1/klines"

async def _get_klines(symbol: str, interval: str, market: str, limit: int = 200):
    if _SESSION is None:
        raise RuntimeError("HTTP session não definida (set_session).")

    url = SPOT if market == "spot" else FUTURES
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    async with _SESSION.get(url, params=params, timeout=12) as r:
        r.raise_for_status()
        return await r.json()

def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema

def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # suavização simples (Wilder)
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = (-diff) if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    return rsi

def _swing_levels(highs: List[float], lows: List[float], lookback: int = 20) -> Tuple[Optional[float], Optional[float]]:
    if len(highs) < 2 or len(lows) < 2:
        return None, None
    lb = min(lookback, len(highs))
    swing_high = max(highs[-lb:])
    swing_low = min(lows[-lb:])
    return swing_high, swing_low

def _cooldown_ok(symbol: str, market: str, interval: str, kind: str, cooldown_min: int) -> bool:
    key = (symbol, market, interval, kind)
    now = time.time()
    last = _LAST.get(key, 0.0)
    if (now - last) < cooldown_min * 60:
        return False
    _LAST[key] = now
    return True

def _detect_signals(symbol: str, market: str, interval: str, highs: List[float], lows: List[float], closes: List[float], cooldown_min: int):
    out = []
    if len(closes) < 60:
        return out

    price = closes[-1]
    ema20 = _ema(closes[-80:], 20)
    ema50 = _ema(closes[-120:], 50)
    rsi14 = _rsi(closes[-200:], 14)

    swing_high, swing_low = _swing_levels(highs, lows, 20)

    # ─────────────
    # Setup 1: EMA20 cruzando EMA50 (tendência)
    # ─────────────
    if ema20 is not None and ema50 is not None:
        # checa cruzamento com base nas EMAs recalculadas com janela deslocada (aprox.)
        ema20_prev = _ema(closes[-81:-1], 20)
        ema50_prev = _ema(closes[-121:-1], 50)

        if ema20_prev is not None and ema50_prev is not None:
            if ema20_prev <= ema50_prev and ema20 > ema50:
                kind = "EMA_CROSS_UP"
                if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                    out.append({
                        "symbol": symbol,
                        "market": market,
                        "interval": interval,
                        "kind": "EMA20 cruzou acima EMA50",
                        "bias": "LONG",
                        "price": price,
                        "rsi": rsi14,
                        "ema_fast": ema20,
                        "ema_slow": ema50,
                        "invalidation": f"Abaixo do swing low (~{swing_low})" if swing_low else None,
                        "message": "Tendência altista *educacional* detectada (EMA20 > EMA50). Considere apenas como estudo/paper.",
                    })

            if ema20_prev >= ema50_prev and ema20 < ema50:
                kind = "EMA_CROSS_DOWN"
                if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                    out.append({
                        "symbol": symbol,
                        "market": market,
                        "interval": interval,
                        "kind": "EMA20 cruzou abaixo EMA50",
                        "bias": "SHORT",
                        "price": price,
                        "rsi": rsi14,
                        "ema_fast": ema20,
                        "ema_slow": ema50,
                        "invalidation": f"Acima do swing high (~{swing_high})" if swing_high else None,
                        "message": "Tendência baixista *educacional* detectada (EMA20 < EMA50). Considere apenas como estudo/paper.",
                    })

    # ─────────────
    # Setup 2: Breakout simples de 20 candles (educacional)
    # ─────────────
    if swing_high is not None and swing_low is not None:
        if price > swing_high:
            kind = "BREAKOUT_UP"
            if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                out.append({
                    "symbol": symbol,
                    "market": market,
                    "interval": interval,
                    "kind": "Breakout acima do topo 20",
                    "bias": "LONG",
                    "price": price,
                    "rsi": rsi14,
                    "ema_fast": ema20,
                    "ema_slow": ema50,
                    "invalidation": f"Retorno abaixo ~{swing_high}",
                    "message": "Rompimento *educacional* acima do topo recente (20 candles). Use apenas como referência/paper.",
                })

        if price < swing_low:
            kind = "BREAKOUT_DOWN"
            if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                out.append({
                    "symbol": symbol,
                    "market": market,
                    "interval": interval,
                    "kind": "Breakdown abaixo do fundo 20",
                    "bias": "SHORT",
                    "price": price,
                    "rsi": rsi14,
                    "ema_fast": ema20,
                    "ema_slow": ema50,
                    "invalidation": f"Retorno acima ~{swing_low}",
                    "message": "Rompimento *educacional* abaixo do fundo recente (20 candles). Use apenas como referência/paper.",
                })

    # ─────────────
    # Setup 3: RSI extremos (só alerta, sem “entrada”)
    # ─────────────
    if rsi14 is not None:
        if rsi14 >= 75:
            kind = "RSI_OVERBOUGHT"
            if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                out.append({
                    "symbol": symbol,
                    "market": market,
                    "interval": interval,
                    "kind": "RSI alto (>=75)",
                    "bias": "NEUTRAL",
                    "price": price,
                    "rsi": rsi14,
                    "ema_fast": ema20,
                    "ema_slow": ema50,
                    "invalidation": None,
                    "message": "RSI muito alto: pode indicar esticamento. *Alerta educacional*.",
                })
        if rsi14 <= 25:
            kind = "RSI_OVERSOLD"
            if _cooldown_ok(symbol, market, interval, kind, cooldown_min):
                out.append({
                    "symbol": symbol,
                    "market": market,
                    "interval": interval,
                    "kind": "RSI baixo (<=25)",
                    "bias": "NEUTRAL",
                    "price": price,
                    "rsi": rsi14,
                    "ema_fast": ema20,
                    "ema_slow": ema50,
                    "invalidation": None,
                    "message": "RSI muito baixo: pode indicar esticamento. *Alerta educacional*.",
                })

    return out

async def scan(symbols: List[str], markets: List[str], interval: str, cooldown_min: int = 60) -> List[dict]:
    out: List[dict] = []
    for market in markets:
        m = market.strip().lower()
        if m not in ("spot", "futures"):
            continue

        for sym in symbols:
            symbol = sym.strip().upper()
            if not symbol:
                continue

            try:
                raw = await _get_klines(symbol, interval, m, limit=200)
                highs = [float(x[2]) for x in raw]
                lows = [float(x[3]) for x in raw]
                closes = [float(x[4]) for x in raw]

                out.extend(_detect_signals(symbol, m, interval, highs, lows, closes, cooldown_min))

            except Exception:
                # silencioso (não derruba) — o main loga por ciclo se necessário
                continue

    return out
