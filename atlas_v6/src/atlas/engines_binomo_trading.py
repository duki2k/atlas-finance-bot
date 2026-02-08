from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pytz
import discord
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")


@dataclass
class TradeEntry:
    ticker: str
    tf: str
    side: str         # "COMPRA" | "VENDA"
    price: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    risk_pct: float
    tp1_pct: float
    tp2_pct: float
    score: float
    why: str
    next_time_str: str


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:,.6f}"


def _masked(label: str, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return f"[{label}]({url})"


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 2:
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


def _next_slot(now: datetime, tf: str) -> datetime:
    now = now.replace(second=0, microsecond=0)
    if tf == "1m":
        return now + timedelta(minutes=1)
    if tf == "5m":
        nm = ((now.minute // 5) + 1) * 5
        if nm >= 60:
            return now.replace(minute=0) + timedelta(hours=1)
        return now.replace(minute=nm)
    if tf == "15m":
        nm = ((now.minute // 15) + 1) * 15
        if nm >= 60:
            return now.replace(minute=0) + timedelta(hours=1)
        return now.replace(minute=nm)
    # fallback
    return now + timedelta(minutes=1)


class BinomoTradingEngine:
    """
    Binomo = TRADING (qualidade > quantidade).
    Usa YahooData.chart() (dados públicos) para gerar entradas educacionais.
    """

    def __init__(self):
        self.thr = {
            "1m": float(getattr(config, "TRADING_SPIKE_1M", 0.25)),
            "5m": float(getattr(config, "TRADING_SPIKE_5M", 0.60)),
            "15m": float(getattr(config, "TRADING_SPIKE_15M", 1.00)),
        }
        self.min_score = float(getattr(config, "TRADING_MIN_SCORE", 70.0))
        self.ema_fast = int(getattr(config, "TRADING_EMA_FAST", 9))
        self.ema_slow = int(getattr(config, "TRADING_EMA_SLOW", 21))

    def _plan(self, side: str, price: float, atr: float) -> Tuple[float, float, float, float, float, float, float]:
        entry = price
        risk = (1.2 * atr) if atr and atr > 0 else price * 0.0035  # fallback ~0.35%

        if side == "COMPRA":
            stop = entry - risk
            tp1 = entry + risk
            tp2 = entry + 2 * risk
        else:
            stop = entry + risk
            tp1 = entry - risk
            tp2 = entry - 2 * risk

        risk_pct = abs((entry - stop) / entry) * 100.0
        tp1_pct = abs((tp1 - entry) / entry) * 100.0
        tp2_pct = abs((tp2 - entry) / entry) * 100.0
        return entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct

    def _score(self, abs_chg: float, ema_cross: bool, break_like: bool) -> float:
        s = min(abs_chg, 2.5) * 30.0  # 0..75
        if ema_cross:
            s += 18.0
        if break_like:
            s += 12.0
        return s

    async def scan_candidates(self, yahoo, tickers: List[str], tf: str, limit: int = 10) -> List[TradeEntry]:
        """Gera uma lista ranqueada de candidatos (qualidade > quantidade)."""
        now = datetime.now(BR_TZ)
        nxt = _next_slot(now, tf)

        out: List[TradeEntry] = []
        for tkr in tickers:
            try:
                # YahooData.chart(ticker, interval, range_="1d")
                ts, o, h, l, c = await yahoo.chart(tkr, tf, "1d")
                if len(c) < 60:
                    continue

                price = float(c[-1])
                prev = float(c[-2]) if c[-2] else 0.0
                if prev <= 0:
                    continue

                chg = ((price - prev) / prev) * 100.0
                abs_chg = abs(chg)

                # qualidade: precisa bater o threshold do timeframe
                if abs_chg < self.thr.get(tf, 999.0):
                    continue

                side = "COMPRA" if chg > 0 else "VENDA"

                atr = _atr(h, l, c, 14) or 0.0
                entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = self._plan(side, price, atr)

                fast = _ema(c[-80:], self.ema_fast)
                slow = _ema(c[-80:], self.ema_slow)
                fast_prev = _ema(c[-81:-1], self.ema_fast)
                slow_prev = _ema(c[-81:-1], self.ema_slow)

                ema_cross = False
                if None not in (fast, slow, fast_prev, slow_prev):
                    if fast_prev <= slow_prev and fast > slow:
                        ema_cross = True
                        side = "COMPRA"
                    elif fast_prev >= slow_prev and fast < slow:
                        ema_cross = True
                        side = "VENDA"

                # “break-like” simples: candle atual rompendo faixa recente
                lookback = 20
                hi = max(h[-(lookback + 1):-1])
                lo = min(l[-(lookback + 1):-1])
                break_like = (price > hi) or (price < lo)

                score = self._score(abs_chg, ema_cross, break_like)
                if score < self.min_score:
                    continue

                why = f"Candle {tf}: {chg:+.2f}%"
                if ema_cross:
                    why += f" | EMA{self.ema_fast} x EMA{self.ema_slow}"
                if break_like:
                    why += " | rompimento recente"

                out.append(TradeEntry(
                    ticker=tkr,
                    tf=tf,
                    side=side,
                    price=price,
                    entry=entry,
                    stop=stop,
                    tp1=tp1,
                    tp2=tp2,
                    risk_pct=risk_pct,
                    tp1_pct=tp1_pct,
                    tp2_pct=tp2_pct,
                    score=score,
                    why=why,
                    next_time_str=nxt.strftime("%H:%M"),
                ))
            except Exception:
                continue

        out.sort(key=lambda x: x.score, reverse=True)
        return out[: max(1, int(limit))]

    async def scan_best(self, yahoo, tickers: List[str], tf: str) -> Optional[TradeEntry]:
        cand = await self.scan_candidates(yahoo, tickers, tf, limit=1)
        return cand[0] if cand else None

    def build_embed(self, entries: List[TradeEntry], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M BRT")
        title = f"📈 Binomo Trading — {tier.upper()}"
        e = discord.Embed(
            title=title,
            description="Entradas educacionais (qualidade > quantidade).\n🧠 Educacional — não é recomendação financeira.",
            color=0x9B59B6,
        )

        if not entries:
            e.add_field(
                name="📌 Sem entradas válidas",
                value="Nenhum setup forte o suficiente neste ciclo (ou mercado fechado).",
                inline=False,
            )
        else:
            lines = []
            for i, s in enumerate(entries, 1):
                arrow = "⬆️" if s.side == "COMPRA" else "⬇️"
                lines.append(
                    f"**{i}) {arrow} {s.side}** • `{s.ticker}` • **{s.tf}**\n"
                    f"Motivo: {s.why}\n"
                    f"Preço: **{_fmt_price(s.price)}** | Entrada: **{_fmt_price(s.entry)}**\n"
                    f"Stop: **{_fmt_price(s.stop)}** (risco **{s.risk_pct:.2f}%**)\n"
                    f"TP1: **{_fmt_price(s.tp1)}** (**{s.tp1_pct:.2f}%**) | TP2: **{_fmt_price(s.tp2)}** (**{s.tp2_pct:.2f}%**)\n"
                    f"⏱️ Próximo candle: **{s.next_time_str} BRT**"
                )
            e.add_field(name="🎯 Entradas", value="\n\n".join(lines)[:1024], inline=False)

        # CTA (sem “indicação”)
        discord_invite = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()
        binomo_ref = (getattr(config, "BINOMO_REF_LINK", "") or "").strip()

        ctas = []
        if binomo_ref:
            ctas.append(f"🎯 {_masked('Acesse aqui e receba benefícios', binomo_ref)}")
        if discord_invite:
            ctas.append(f"🚀 {_masked('Entre no Discord e acompanhe ao vivo', discord_invite)}")

        if ctas:
            e.add_field(name="✨ Acesso rápido", value="\n".join(ctas)[:1024], inline=False)

        e.set_footer(text=f"Atlas v6 • {now}")
        return e
