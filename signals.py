# signals.py (FINAL)
# Strategy: 15m signals reading Binance + MEXC (Spot/Futures).
# For each symbol, compares both exchanges and chooses ONLY the best opportunity to post.

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
import pytz
import discord

import config

HEADERS = {"User-Agent": "AtlasFinanceBot/1.0"}
BR_TZ = pytz.timezone("America/Sao_Paulo")

# Cooldown: (symbol, market, kind, side) -> last_ts
_COOLDOWN: Dict[Tuple[str, str, str, str], float] = {}

BASE_SCORE = {"BREAKOUT": 85.0, "EMA_CROSS": 65.0, "RSI_EXTREMO": 35.0}

SIDE_LABEL = {
    "LONG": "COMPRA",
    "SHORT": "VENDA",
    "WATCH_LONG": "COMPRA (aguardar confirmação)",
    "WATCH_SHORT": "VENDA (aguardar confirmação)",
}


# ----------------------------
# Utils
# ----------------------------
def _get_json(url: str, params: dict | None = None, timeout: int = 12, retries: int = 2) -> Any:
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.25 * (i + 1))
    return {"_error": str(last_err) if last_err else "unknown"}


def _float(x) -> Optional[float]:
    try:
        f = float(x)
        if f != f:
            return None
        return f
    except Exception:
        return None


def _avg(vals: List[Optional[float]]) -> Optional[float]:
    vs = [v for v in vals if v is not None]
    return (sum(vs) / len(vs)) if vs else None


def _format_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:,.6f}"


def _next_15m_slot(now_brt: datetime) -> Tuple[datetime, int]:
    minute = now_brt.minute
    next_min = ((minute // 15) + 1) * 15
    slot = now_brt.replace(second=0, microsecond=0)
    if next_min >= 60:
        slot = slot.replace(minute=0) + timedelta(hours=1)
        return slot, 0
    return slot.replace(minute=next_min), next_min


def _cooldown_ok(key: Tuple[str, str, str, str], cooldown_minutes: int) -> bool:
    now = time.time()
    last = _COOLDOWN.get(key)
    if last and (now - last) < cooldown_minutes * 60:
        return False
    _COOLDOWN[key] = now
    return True


# ----------------------------
# Indicators
# ----------------------------
def ema(values: List[float], period: int) -> Optional[float]:
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: List[float], period: int = 14) -> Optional[float]:
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


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _swing_low(lows: List[float], lookback: int = 12) -> Optional[float]:
    if not lows:
        return None
    window = lows[-lookback:] if len(lows) >= lookback else lows
    return min(window) if window else None


def _swing_high(highs: List[float], lookback: int = 12) -> Optional[float]:
    if not highs:
        return None
    window = highs[-lookback:] if len(highs) >= lookback else highs
    return max(window) if window else None


# ----------------------------
# Fetch klines (sync)
# ----------------------------
def _parse_binance_klines(rows: list) -> Tuple[List[float], List[float], List[float], List[float]]:
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


def fetch_binance_spot(symbol: str, interval: str = "15m", limit: int = 200):
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


def fetch_binance_futures(symbol: str, interval: str = "15m", limit: int = 200):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    j = _get_json(url, params=params, timeout=12, retries=2)
    if isinstance(j, list) and j:
        return _parse_binance_klines(j)
    return [], [], [], []


def fetch_binance_funding(symbol: str) -> Optional[float]:
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": symbol}
    j = _get_json(url, params=params, timeout=10, retries=1)
    if isinstance(j, dict):
        return _float(j.get("lastFundingRate"))
    return None


def fetch_mexc_spot(symbol: str, interval: str = "15m", limit: int = 200):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    j = _get_json(url, params=params, timeout=12, retries=2)
    if isinstance(j, list) and j:
        return _parse_binance_klines(j)
    return [], [], [], []


def _mexc_contract_symbol(symbol: str) -> str:
    if symbol.endswith("USDT") and "_" not in symbol:
        base = symbol.replace("USDT", "")
        return f"{base}_USDT"
    return symbol


def _mexc_interval(interval: str) -> str:
    return {
        "1m": "Min1",
        "5m": "Min5",
        "15m": "Min15",
        "30m": "Min30",
        "1h": "Min60",
        "4h": "Hour4",
        "1d": "Day1",
    }.get(interval, "Min15")


def fetch_mexc_futures(symbol: str, interval: str = "15m", limit: int = 200):
    bases = ["https://contract.mexc.com", "https://api.mexc.com"]
    sym = _mexc_contract_symbol(symbol)
    itv = _mexc_interval(interval)

    now = int(time.time())
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
            highs = [_float(x) for x in data.get("high", [])]
            lows = [_float(x) for x in data.get("low", [])]
            vols = [_float(x) for x in data.get("vol", [])]
            closes = [x for x in closes if x is not None]
            highs = [x for x in highs if x is not None]
            lows = [x for x in lows if x is not None]
            vols = [x for x in vols if x is not None]
            return closes, highs, lows, vols

    return [], [], [], []


def fetch_mexc_funding(symbol: str) -> Optional[float]:
    bases = ["https://contract.mexc.com", "https://api.mexc.com"]
    sym = _mexc_contract_symbol(symbol)
    for base in bases:
        url = f"{base}/api/v1/contract/funding_rate/{sym}"
        j = _get_json(url, timeout=10, retries=1)
        data = (j or {}).get("data")
        if isinstance(data, dict):
            return _float(data.get("fundingRate"))
    return None


# ----------------------------
# Signal detection + plan
# ----------------------------
@dataclass
class Proposal:
    symbol: str
    market: str
    exchange: str
    kind: str
    side: str
    price: float
    rsi: Optional[float]
    vol_mult: Optional[float]
    funding: Optional[float]
    score: float
    note: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    risk_pct: float
    tp1_pct: float
    tp2_pct: float
    entry_time_brt: datetime
    entry_minute: int
    entry_rule: str


def _score(kind: str, side: str, vol_mult: Optional[float], r: Optional[float], funding: Optional[float], extra: float = 0.0) -> float:
    s = BASE_SCORE.get(kind, 40.0)
    vm = vol_mult if (vol_mult is not None and vol_mult > 0) else 1.0
    s += min(vm, 3.0) * 10.0
    if r is not None:
        s += min(abs(r - 50.0), 30.0) * 0.6
    if side.startswith("WATCH_"):
        s -= 12.0
    if funding is not None:
        s -= min(abs(funding) * 100000.0, 15.0)
    return max(0.0, s + extra)


def _build_plan(kind: str, side: str, price: float, highs: List[float], lows: List[float], closes: List[float], now_brt: datetime):
    a = atr(highs, lows, closes, 14) or 0.0
    slot_dt, slot_min = _next_15m_slot(now_brt)
    buf = 0.0005  # 0.05%

    entry = price
    entry_rule = f"Entrada no inicio do proximo candle 15m ({slot_dt.strftime('%H:%M')} BRT)."

    if kind == "BREAKOUT" and highs and len(highs) >= 25:
        topo_20 = max(highs[-21:-1])
        entry = topo_20 * (1.0 + buf)
        entry_rule = f"Entrar se romper {_format_price(entry)} (topo 20 + buffer) no proximo candle 15m ({slot_dt.strftime('%H:%M')} BRT)."
        sl = _swing_low(lows, 12) or (price - 1.5 * a if a else price * 0.985)
        stop = sl * (1.0 - buf)

    elif kind == "EMA_CROSS":
        if a:
            stop = price - 1.2 * a
        else:
            sl = _swing_low(lows, 10) or price * 0.985
            stop = sl * (1.0 - buf)

    else:  # RSI_EXTREMO
        if side == "WATCH_LONG":
            trigger = (_swing_high(highs, 3) or price) * (1.0 + buf)
            entry = trigger
            entry_rule = f"Aguardar confirmacao: entrar se romper {_format_price(entry)} (maxima recente + buffer) no proximo candle 15m ({slot_dt.strftime('%H:%M')} BRT)."
            sl = _swing_low(lows, 8) or (price - 1.5 * a if a else price * 0.985)
            stop = sl * (1.0 - buf)
        else:
            trigger = (_swing_low(lows, 3) or price) * (1.0 - buf)
            entry = trigger
            entry_rule = f"Aguardar confirmacao: entrar se perder {_format_price(entry)} (minima recente - buffer) no proximo candle 15m ({slot_dt.strftime('%H:%M')} BRT)."
            sh = _swing_high(highs, 8) or (price + 1.5 * a if a else price * 1.015)
            stop = sh * (1.0 + buf)

    if side in ("SHORT", "WATCH_SHORT"):
        if a:
            stop = max(stop, price + 1.2 * a)
        else:
            sh = _swing_high(highs, 10) or price * 1.015
            stop = max(stop, sh * (1.0 + buf))
        risk = abs(stop - entry)
        tp1 = entry - 1.0 * risk
        tp2 = entry - 2.0 * risk
    else:
        risk = abs(entry - stop)
        tp1 = entry + 1.0 * risk
        tp2 = entry + 2.0 * risk

    risk_pct = (risk / entry) * 100.0 if entry else 0.0
    tp1_pct = abs((tp1 - entry) / entry) * 100.0 if entry else 0.0
    tp2_pct = abs((tp2 - entry) / entry) * 100.0 if entry else 0.0

    return entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule


def _detect(symbol: str, market: str, exchange: str, closes: List[float], highs: List[float], lows: List[float], vols: List[float], funding: Optional[float], now_brt: datetime) -> List[Proposal]:
    if not closes or len(closes) < 40:
        return []

    price = closes[-1]
    fast_now = ema(closes[-80:], 9)
    slow_now = ema(closes[-80:], 21)
    fast_prev = ema(closes[-81:-1], 9) if len(closes) >= 81 else None
    slow_prev = ema(closes[-81:-1], 21) if len(closes) >= 81 else None

    r = rsi(closes[-40:], 14)
    vol_now = vols[-1] if vols else None
    vol_avg = _avg(vols[-21:-1]) if vols and len(vols) >= 21 else None
    vol_mult = (vol_now / vol_avg) if (vol_now and vol_avg and vol_avg > 0) else None

    out: List[Proposal] = []

    # EMA cross LONG
    if fast_prev is not None and slow_prev is not None and fast_now is not None and slow_now is not None:
        if fast_prev <= slow_prev and fast_now > slow_now:
            kind, side = "EMA_CROSS", "LONG"
            extra = min(abs((fast_now - slow_now) / price) * 100.0, 1.0) * 20.0 if price else 0.0
            entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule = _build_plan(kind, side, price, highs, lows, closes, now_brt)
            score = _score(kind, side, vol_mult, r, funding, extra=extra)
            out.append(Proposal(symbol, market, exchange, kind, side, price, r, vol_mult, funding, score,
                                "EMA9 cruzou acima da EMA21", entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule))

        # EMA cross SHORT: só faz sentido como entrada em FUTURES (spot = saída)
        elif market == "futures" and fast_prev >= slow_prev and fast_now < slow_now:
            kind, side = "EMA_CROSS", "SHORT"
            extra = min(abs((fast_now - slow_now) / price) * 100.0, 1.0) * 20.0 if price else 0.0
            entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule = _build_plan(kind, side, price, highs, lows, closes, now_brt)
            score = _score(kind, side, vol_mult, r, funding, extra=extra)
            out.append(Proposal(symbol, market, exchange, kind, side, price, r, vol_mult, funding, score,
                                "EMA9 cruzou abaixo da EMA21", entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule))

    # Breakout long
    if highs and len(highs) >= 25:
        topo_20 = max(highs[-21:-1])
        if topo_20 and price > topo_20:
            margin_pct = ((price / topo_20) - 1.0) * 100.0
            extra = min(max(margin_pct, 0.0), 1.0) * 25.0 + (12.0 if (vol_mult is not None and vol_mult >= 1.4) else 0.0)
            kind, side = "BREAKOUT", "LONG"
            entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule = _build_plan(kind, side, price, highs, lows, closes, now_brt)
            score = _score(kind, side, vol_mult, r, funding, extra=extra)
            out.append(Proposal(symbol, market, exchange, kind, side, price, r, vol_mult, funding, score,
                                "Rompimento do topo (20 candles) + volume", entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule))

    # RSI extreme (watch)
    if r is not None:
        if r <= 25:
            kind, side = "RSI_EXTREMO", "WATCH_LONG"
            entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule = _build_plan(kind, side, price, highs, lows, closes, now_brt)
            score = _score(kind, side, vol_mult, r, funding)
            out.append(Proposal(symbol, market, exchange, kind, side, price, r, vol_mult, funding, score,
                                "RSI muito baixo (possivel exaustao de venda)", entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule))
        elif r >= 75:
            kind, side = "RSI_EXTREMO", "WATCH_SHORT"
            entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule = _build_plan(kind, side, price, highs, lows, closes, now_brt)
            score = _score(kind, side, vol_mult, r, funding)
            out.append(Proposal(symbol, market, exchange, kind, side, price, r, vol_mult, funding, score,
                                "RSI muito alto (possivel exaustao de compra)", entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct, slot_dt, slot_min, entry_rule))

    return out


def _best_for(symbol: str, market: str, exchange: str, interval: str, now_brt: datetime) -> List[Proposal]:
    exchange = exchange.lower().strip()
    market = market.lower().strip()
    funding = None

    if market == "spot":
        if exchange == "binance":
            closes, highs, lows, vols = fetch_binance_spot(symbol, interval=interval)
        elif exchange == "mexc":
            closes, highs, lows, vols = fetch_mexc_spot(symbol, interval=interval)
        else:
            return []
    else:
        if exchange == "binance":
            closes, highs, lows, vols = fetch_binance_futures(symbol, interval=interval)
            funding = fetch_binance_funding(symbol)
        elif exchange == "mexc":
            closes, highs, lows, vols = fetch_mexc_futures(symbol, interval=interval)
            funding = fetch_mexc_funding(symbol)
        else:
            return []
    return _detect(symbol, market, exchange, closes, highs, lows, vols, funding, now_brt)


def _pick_best(proposals: List[Proposal]) -> Optional[Proposal]:
    if not proposals:
        return None
    proposals.sort(key=lambda p: p.score, reverse=True)
    best = proposals[0]
    # tie-breaker: prefer Binance
    for p in proposals[1:]:
        if abs(p.score - best.score) < 0.01 and best.exchange != "binance" and p.exchange == "binance":
            best = p
    return best


def scan_best_signals() -> Dict[str, List[Proposal]]:
    symbols = list(getattr(config, "SINAIS_PARES", []))
    exchanges = list(getattr(config, "SINAIS_EXCHANGES", ["binance", "mexc"]))
    interval = getattr(config, "SINAIS_TIMEFRAME", "15m") or "15m"
    cooldown_minutes = int(getattr(config, "SINAIS_COOLDOWN_MINUTES", 60) or 60)
    max_spot = int(getattr(config, "SINAIS_MAX_POR_CICLO_SPOT", 8) or 8)
    max_fut = int(getattr(config, "SINAIS_MAX_POR_CICLO_FUTURES", 8) or 8)

    now_brt = datetime.now(BR_TZ)

    spot_out: List[Proposal] = []
    fut_out: List[Proposal] = []
    errors = 0

    for sym in symbols:
        try:
            spot_candidates: List[Proposal] = []
            fut_candidates: List[Proposal] = []

            for ex in exchanges:
                spot_candidates.extend(_best_for(sym, "spot", ex, interval, now_brt))
                time.sleep(0.08)

            for ex in exchanges:
                fut_candidates.extend(_best_for(sym, "futures", ex, interval, now_brt))
                time.sleep(0.08)

            best_spot = _pick_best(spot_candidates)
            best_fut = _pick_best(fut_candidates)

            # Best opportunity now (spot vs futures)
            best = best_spot or best_fut
            if best_spot and best_fut:
                best = best_spot if best_spot.score >= best_fut.score else best_fut

            if not best:
                continue

            key = (best.symbol, best.market, best.kind, best.side)
            if not _cooldown_ok(key, cooldown_minutes):
                continue

            if best.market == "spot":
                spot_out.append(best)
            else:
                fut_out.append(best)

        except Exception:
            errors += 1

    spot_out.sort(key=lambda p: p.score, reverse=True)
    fut_out.sort(key=lambda p: p.score, reverse=True)

    return {"spot": spot_out[:max_spot], "futures": fut_out[:max_fut], "errors": errors}


def build_embed(p: Proposal) -> discord.Embed:
    if p.side in ("LONG", "WATCH_LONG"):
        color = 0x2ECC71
    elif p.side in ("SHORT", "WATCH_SHORT"):
        color = 0xE74C3C
    else:
        color = 0xF1C40F

    title = f"📌 Sinal 15m — {p.symbol} ({p.market.upper()})"
    desc = (
        f"**Direcao:** **{SIDE_LABEL.get(p.side, p.side)}**  |  **Exchange:** **{p.exchange.upper()}**\n"
        f"**Motivo:** {p.note}\n\n"
        "🧠 Educacional — nao e recomendacao financeira."
    )

    e = discord.Embed(title=title, description=desc, color=color)
    e.add_field(name="📍 Preco atual", value=_format_price(p.price), inline=True)

    e.add_field(
        name="🎯 Entrada (como fazer)",
        value=f"{_format_price(p.entry)}\n{p.entry_rule}",
        inline=False,
    )

    e.add_field(
        name="🛡️ Stop",
        value=f"{_format_price(p.stop)}\nRisco: **{p.risk_pct:.2f}%**",
        inline=True,
    )

    e.add_field(
        name="🏁 Alvos",
        value=(
            f"TP1: {_format_price(p.tp1)} (**{p.tp1_pct:.2f}%**)\n"
            f"TP2: {_format_price(p.tp2)} (**{p.tp2_pct:.2f}%**)"
        ),
        inline=True,
    )

    e.add_field(
        name="⏱️ Minuto para entrada",
        value=f"Proximo candle 15m: **{p.entry_time_brt.strftime('%H:%M')} BRT** (minuto **{p.entry_minute:02d}**)",
        inline=False,
    )

    ind = []
    if p.rsi is not None:
        ind.append(f"RSI14: {p.rsi:.1f}")
    if p.vol_mult is not None:
        ind.append(f"Vol: {p.vol_mult:.2f}x")
    ind.append(f"Score: {p.score:.1f}")
    if p.market == "futures" and p.funding is not None:
        ind.append(f"Funding: {p.funding*100:.4f}%")

    e.add_field(name="📊 Indicadores", value=" | ".join(ind), inline=False)
    e.set_footer(text=f"Atlas Signals • {datetime.now(BR_TZ).strftime('%d/%m/%Y %H:%M')} BRT")
    return e


async def scan_and_post(client: discord.Client, force: bool = False) -> Dict[str, int]:
    if not getattr(config, "SINAIS_ATIVOS", False):
        return {"spot": 0, "futures": 0}

    spot_id = int(getattr(config, "CANAL_SINAIS_SPOT", 0) or 0)
    fut_id = int(getattr(config, "CANAL_SINAIS_FUTURES", 0) or 0)

    spot_chan = client.get_channel(spot_id) if spot_id else None
    fut_chan = client.get_channel(fut_id) if fut_id else None

    if not spot_chan and not fut_chan:
        return {"spot": 0, "futures": 0}

    result = await asyncio.to_thread(scan_best_signals)
    spot = result.get("spot", [])
    fut = result.get("futures", [])

    sent_spot = 0
    sent_fut = 0

    force_note = "" if not force else "\n\n⚙️ Scan manual acionado por comando."

    for p in spot:
        if not spot_chan:
            continue
        emb = build_embed(p)
        if force_note:
            emb.description = (emb.description or "") + force_note
        await spot_chan.send(embed=emb)
        sent_spot += 1

    for p in fut:
        if not fut_chan:
            continue
        emb = build_embed(p)
        if force_note:
            emb.description = (emb.description or "") + force_note
        await fut_chan.send(embed=emb)
        sent_fut += 1

    return {"spot": sent_spot, "futures": sent_fut}
