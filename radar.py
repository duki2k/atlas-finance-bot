from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
import discord
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Signal:
    tier: str               # "membro" | "investidor"
    interval: str           # "1m" | "5m" | "15m" | "4h"
    kind: str               # "SPIKE" | "BREAK" | "EMA"
    symbol: str
    side: str               # "COMPRA" | "VENDA" (spot venda = reduzir/proteger)
    price: float

    entry: float
    stop: float
    tp1: float
    tp2: float

    risk_pct: float
    tp1_pct: float
    tp2_pct: float

    why: str
    score: float
    next_time_str: str
    next_minute: int

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2:
        return None
    trs = []
    for i in range(1, n):
        h = highs[i]; l = lows[i]; pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period

def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:,.6f}"

def _next_slot(now: datetime, interval: str) -> Tuple[datetime, int]:
    now = now.replace(second=0, microsecond=0)
    if interval == "1m":
        nxt = now + timedelta(minutes=1)
        return nxt, nxt.minute
    if interval == "5m":
        m = now.minute
        nm = ((m // 5) + 1) * 5
        if nm >= 60:
            nxt = now.replace(minute=0) + timedelta(hours=1)
            return nxt, 0
        nxt = now.replace(minute=nm)
        return nxt, nm
    if interval == "15m":
        m = now.minute
        nm = ((m // 15) + 1) * 15
        if nm >= 60:
            nxt = now.replace(minute=0) + timedelta(hours=1)
            return nxt, 0
        nxt = now.replace(minute=nm)
        return nxt, nm
    # 4h
    nxt = now + timedelta(hours=4)
    nxt = nxt.replace(minute=0)
    return nxt, 0

def _cooldown_minutes(tier: str, interval: str, kind: str) -> int:
    return int(config.COOLDOWN_MINUTES.get((tier, interval, kind), 30))

class RadarEngine:
    def __init__(self):
        self.last_sent: Dict[Tuple[str, str, str, str], float] = {}
        self.paused_until_ts = 0.0

    def paused(self) -> bool:
        return datetime.now(BR_TZ).timestamp() < self.paused_until_ts

    def pause_minutes(self, minutes: int):
        self.paused_until_ts = (datetime.now(BR_TZ) + timedelta(minutes=minutes)).timestamp()

    def resume(self):
        self.paused_until_ts = 0.0

    def _can_send(self, s: Signal) -> bool:
        key = (s.tier, s.interval, s.kind, s.symbol)
        now_ts = datetime.now(BR_TZ).timestamp()
        last = self.last_sent.get(key, 0.0)
        cd = _cooldown_minutes(s.tier, s.interval, s.kind)
        if (now_ts - last) < cd * 60:
            return False
        self.last_sent[key] = now_ts
        return True

    def _plan(self, side: str, price: float, a: float) -> Tuple[float, float, float, float, float, float, float]:
        # entrada no próximo candle no preço/nível (educacional)
        entry = price
        risk = (1.2 * a) if a and a > 0 else price * 0.005  # fallback 0.5%

        if side == "COMPRA":
            stop = entry - risk
            tp1 = entry + risk
            tp2 = entry + 2 * risk
        else:
            # spot: “VENDA” = reduzir/realizar/proteger; stop acima
            stop = entry + risk
            tp1 = entry - risk
            tp2 = entry - 2 * risk

        risk_pct = abs((entry - stop) / entry) * 100.0
        tp1_pct = abs((tp1 - entry) / entry) * 100.0
        tp2_pct = abs((tp2 - entry) / entry) * 100.0
        return entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct

    def _score(self, kind: str, abs_pct: float, vol_mult: Optional[float]) -> float:
        base = {"SPIKE": 65, "BREAK": 85, "EMA": 60}.get(kind, 50)
        s = base + min(abs_pct, 5.0) * 10.0
        if vol_mult is not None:
            s += min(vol_mult, 3.0) * 10.0
        return s

    def build_embed(self, s: Signal) -> discord.Embed:
        color = 0x2ECC71 if s.side == "COMPRA" else 0xE74C3C
        title = f"🚨 Entrada {s.interval} — {s.side} (SPOT)"
        desc = (
            f"**Ativo:** `{s.symbol}`\n"
            f"**Motivo:** {s.why}\n"
            f"**Camada:** `{s.tier.upper()}`\n\n"
            "🧠 Educacional — não é recomendação financeira."
        )
        e = discord.Embed(title=title, description=desc, color=color)
        e.add_field(name="💲 Preço", value=_fmt_price(s.price), inline=True)
        e.add_field(name="🎯 Entrada", value=_fmt_price(s.entry), inline=True)
        e.add_field(name="🛡️ Stop", value=f"{_fmt_price(s.stop)}\nRisco: **{s.risk_pct:.2f}%**", inline=True)
        e.add_field(
            name="🏁 Alvos",
            value=f"TP1: {_fmt_price(s.tp1)} (**{s.tp1_pct:.2f}%**)\nTP2: {_fmt_price(s.tp2)} (**{s.tp2_pct:.2f}%**)",
            inline=False,
        )
        e.add_field(
            name="⏱️ Minuto de entrada",
            value=f"Próximo candle: **{s.next_time_str} BRT** (minuto **{s.next_minute:02d}**)",
            inline=False,
        )
        e.set_footer(text=f"Atlas Radar Pro • {datetime.now(BR_TZ).strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, s: Signal) -> str:
        return (
            f"🚨 Atlas Radar Pro — {s.side} (SPOT) [{s.interval}] / {s.tier.upper()}\n"
            f"Ativo: {s.symbol}\n"
            f"Preço: {_fmt_price(s.price)}\n"
            f"Entrada: {_fmt_price(s.entry)}\n"
            f"Stop: {_fmt_price(s.stop)} (risco {s.risk_pct:.2f}%)\n"
            f"TP1: {_fmt_price(s.tp1)} ({s.tp1_pct:.2f}%)\n"
            f"TP2: {_fmt_price(s.tp2)} ({s.tp2_pct:.2f}%)\n"
            f"Minuto: {s.next_time_str} BRT\n"
            f"Motivo: {s.why}\n\n"
            "Educacional — não é recomendação financeira."
        )

    async def scan(self, b, tier: str, interval: str, symbols: List[str]) -> List[Signal]:
        rule = config.RULES[interval]
        lookback = int(rule["lookback"])
        atr_period = int(rule["atr_period"])
        vol_mult_thr = float(rule["vol_mult"])

        now = datetime.now(BR_TZ)
        nxt_dt, nxt_min = _next_slot(now, interval)

        out: List[Signal] = []

        # limite mínimo de candles para indicadores
        limit = max(lookback + 5, 60) if interval in ("1m", "5m", "15m") else max(lookback + 5, 120)

        for sym in symbols:
            t, o, h, l, c, v = await b.klines(sym, interval, limit)
            if len(c) < lookback + 5:
                continue

            price = c[-1]
            prev = c[-2]
            chg = ((price - prev) / prev) * 100.0 if prev > 0 else 0.0
            abs_chg = abs(chg)

            a = atr(h, l, c, atr_period) or 0.0

            # volume mult
            vm = None
            if len(v) >= lookback + 2:
                base = v[-(lookback+1):-1]
                avg = (sum(base) / len(base)) if base else 0.0
                if avg > 0:
                    vm = v[-1] / avg

            # 1) SPIKE (interval específico)
            spike_thr = float(config.SPIKE_PCT.get(interval, 999.0))
            if abs_chg >= spike_thr:
                side = "COMPRA" if chg > 0 else "VENDA"
                entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, a)
                out.append(Signal(
                    tier=tier, interval=interval, kind="SPIKE", symbol=sym, side=side, price=price,
                    entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=risk_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
                    why=f"Movimento do candle {interval}: {chg:+.2f}%",
                    score=self._score("SPIKE", abs_chg, vm),
                    next_time_str=nxt_dt.strftime("%H:%M"),
                    next_minute=nxt_min,
                ))

            # 2) BREAKOUT/BREAKDOWN (lookback)
            hi = max(h[-(lookback+1):-1])
            lo = min(l[-(lookback+1):-1])
            if vm is None or vm >= vol_mult_thr:
                if price > hi:
                    side = "COMPRA"
                    entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, a)
                    out.append(Signal(
                        tier=tier, interval=interval, kind="BREAK", symbol=sym, side=side, price=price,
                        entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=risk_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
                        why=f"Rompimento acima da máxima ({lookback} candles) + volume.",
                        score=self._score("BREAK", abs_chg, vm) + 10,
                        next_time_str=nxt_dt.strftime("%H:%M"),
                        next_minute=nxt_min,
                    ))
                elif price < lo:
                    side = "VENDA"
                    entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, a)
                    out.append(Signal(
                        tier=tier, interval=interval, kind="BREAK", symbol=sym, side=side, price=price,
                        entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=risk_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
                        why=f"Perda abaixo da mínima ({lookback} candles) + volume.",
                        score=self._score("BREAK", abs_chg, vm) + 10,
                        next_time_str=nxt_dt.strftime("%H:%M"),
                        next_minute=nxt_min,
                    ))

            # 3) EMA cross (tendência)
            fast = ema(c[-60:], int(config.EMA_FAST))
            slow = ema(c[-60:], int(config.EMA_SLOW))
            fast_prev = ema(c[-61:-1], int(config.EMA_FAST)) if len(c) >= 61 else None
            slow_prev = ema(c[-61:-1], int(config.EMA_SLOW)) if len(c) >= 61 else None

            if None not in (fast, slow, fast_prev, slow_prev):
                if fast_prev <= slow_prev and fast > slow:
                    side = "COMPRA"
                    entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, a)
                    out.append(Signal(
                        tier=tier, interval=interval, kind="EMA", symbol=sym, side=side, price=price,
                        entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=risk_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
                        why="Tendência virou pra cima (EMA9 ↑ EMA21).",
                        score=self._score("EMA", abs_chg, vm),
                        next_time_str=nxt_dt.strftime("%H:%M"),
                        next_minute=nxt_min,
                    ))
                elif fast_prev >= slow_prev and fast < slow:
                    side = "VENDA"
                    entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, a)
                    out.append(Signal(
                        tier=tier, interval=interval, kind="EMA", symbol=sym, side=side, price=price,
                        entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=risk_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
                        why="Tendência virou pra baixo (EMA9 ↓ EMA21) — em SPOT é proteção/realização.",
                        score=self._score("EMA", abs_chg, vm),
                        next_time_str=nxt_dt.strftime("%H:%M"),
                        next_minute=nxt_min,
                    ))

        out.sort(key=lambda s: s.score, reverse=True)
        limit_out = int(config.MAX_ALERTS_PER_CYCLE.get(tier, 5))
        return out[:limit_out]
