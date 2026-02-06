from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import discord
import pytz
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Entry:
    tf: str
    ticker: str
    side: str   # "COMPRA" | "VENDA"
    price: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    risk_pct: float
    why: str
    score: float
    next_time_str: str
    next_minute: int

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period: return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2: return None
    trs = []
    for i in range(1, n):
        h = highs[i]; l = lows[i]; pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period: return None
    return sum(trs[-period:]) / period

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1: return f"{p:,.4f}"
    return f"{p:,.6f}"

def _next_slot(now: datetime, tf: str) -> Tuple[datetime, int]:
    now = now.replace(second=0, microsecond=0)
    if tf == "5m":
        m = now.minute
        nm = ((m // 5) + 1) * 5
        if nm >= 60:
            nxt = now.replace(minute=0) + timedelta(hours=1)
            return nxt, 0
        return now.replace(minute=nm), nm
    if tf == "15m":
        m = now.minute
        nm = ((m // 15) + 1) * 15
        if nm >= 60:
            nxt = now.replace(minute=0) + timedelta(hours=1)
            return nxt, 0
        return now.replace(minute=nm), nm
    # fallback
    nxt = now + timedelta(minutes=1)
    return nxt, nxt.minute

class BinomoTradingEngine:
    def __init__(self):
        self.fast = 9
        self.slow = 21

    def _plan(self, side: str, price: float, a: float) -> Tuple[float, float, float, float, float]:
        entry = price
        risk = (1.2 * a) if a and a > 0 else price * 0.004  # fallback ~0.4%

        if side == "COMPRA":
            stop = entry - risk
            tp1 = entry + risk
            tp2 = entry + 2 * risk
        else:
            stop = entry + risk
            tp1 = entry - risk
            tp2 = entry - 2 * risk

        risk_pct = abs((entry - stop) / entry) * 100.0 if entry else 0.0
        return entry, stop, tp1, tp2, risk_pct

    def _score(self, abs_chg: float, crossed: bool) -> float:
        s = abs_chg * 120.0
        if crossed:
            s += 35.0
        return s

    async def scan(self, yahoo, tickers: List[str], tf: str, max_out: int) -> List[Entry]:
        now = datetime.now(BR_TZ)
        nxt_dt, nxt_min = _next_slot(now, tf)

        out: List[Entry] = []

        for t in tickers:
            try:
                o, h, l, c = await yahoo.candles(t, tf)
                if len(c) < 40:
                    continue

                price = float(c[-1])
                prev = float(c[-2])
                chg = ((price - prev) / prev) * 100.0 if prev else 0.0
                abs_chg = abs(chg)

                a = atr([float(x) for x in h], [float(x) for x in l], [float(x) for x in c], 14) or 0.0

                # regras simples e úteis: spike + EMA cross
                crossed = False
                fast = ema([float(x) for x in c][-60:], self.fast)
                slow = ema([float(x) for x in c][-60:], self.slow)
                fast_prev = ema([float(x) for x in c][-61:-1], self.fast)
                slow_prev = ema([float(x) for x in c][-61:-1], self.slow)

                if None not in (fast, slow, fast_prev, slow_prev):
                    if fast_prev <= slow_prev and fast > slow:
                        crossed = True
                        side = "COMPRA"
                        why = "EMA9 cruzou acima da EMA21."
                    elif fast_prev >= slow_prev and fast < slow:
                        crossed = True
                        side = "VENDA"
                        why = "EMA9 cruzou abaixo da EMA21."
                    else:
                        side = "COMPRA" if chg > 0 else "VENDA"
                        why = f"Movimento do candle ({tf}): {chg:+.2f}%."
                else:
                    side = "COMPRA" if chg > 0 else "VENDA"
                    why = f"Movimento do candle ({tf}): {chg:+.2f}%."

                # filtro: evitar mandar ruído
                if abs_chg < (0.08 if tf == "5m" else 0.12) and not crossed:
                    continue

                entry, stop, tp1, tp2, risk_pct = self._plan(side, price, a)
                score = self._score(abs_chg, crossed)

                out.append(Entry(
                    tf=tf, ticker=t, side=side, price=price,
                    entry=entry, stop=stop, tp1=tp1, tp2=tp2,
                    risk_pct=risk_pct, why=why, score=score,
                    next_time_str=nxt_dt.strftime("%H:%M"),
                    next_minute=nxt_min,
                ))
            except Exception:
                continue

        out.sort(key=lambda x: x.score, reverse=True)
        return out[:max_out]

    def build_embed(self, entries: List[Entry], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        ref = str(getattr(config, "BINOMO_REF_LINK", "") or "").strip()

        if not entries:
            e = discord.Embed(
                title=f"📉 Binomo Trading — {tier.upper()} (sem entradas)",
                description="Sem entradas válidas neste ciclo (ou mercado fechado).\n🧠 Educacional — não é recomendação financeira.",
                color=0x95A5A6,
            )
            if ref:
                e.add_field(name="🔗 Binomo (indicação)", value=ref, inline=False)
            e.set_footer(text=f"Atlas v6 • {now} BRT")
            return e

        e = discord.Embed(
            title=f"📉 Binomo Trading — {tier.upper()}",
            description="Entradas educacionais (curto prazo).\n🧠 Educacional — não é recomendação financeira.",
            color=0x9B59B6,
        )

        for idx, s in enumerate(entries, start=1):
            arrow = "⬆️" if s.side == "COMPRA" else "⬇️"
            e.add_field(
                name=f"{idx}) {arrow} {s.side} • {s.tf} • {s.ticker}",
                value=(
                    f"Preço: **{_fmt(s.price)}** | Entrada: **{_fmt(s.entry)}**\n"
                    f"Stop: **{_fmt(s.stop)}** (risco **{s.risk_pct:.2f}%**)\n"
                    f"TP1: **{_fmt(s.tp1)}** • TP2: **{_fmt(s.tp2)}**\n"
                    f"Minuto: **{s.next_time_str} BRT** (min **{s.next_minute:02d}**)\n"
                    f"Motivo: {s.why}"
                ),
                inline=False,
            )

        if ref:
            e.add_field(name="🔗 Binomo (indicação)", value=ref, inline=False)

        e.set_footer(text=f"Atlas v6 • {now} BRT")
        return e
