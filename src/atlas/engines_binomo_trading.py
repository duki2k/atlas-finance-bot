from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pytz
import discord
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")


@dataclass
class TradeSignal:
    symbol: str
    timeframe: str  # "5m" | "15m"
    side: str       # "COMPRA" | "VENDA"
    price: float

    entry: float
    stop: float
    tp1: float
    tp2: float

    risk_pct: float
    tp1_pct: float
    tp2_pct: float

    why: str
    next_time_str: str
    next_minute: int


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
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


def _plan(side: str, price: float) -> Tuple[float, float, float, float, float, float, float]:
    entry = price
    risk = price * 0.0035  # 0.35% padrão (educacional)

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


def _masked(label: str, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return f"[{label}]({url})"


class BinomoTradingEngine:
    """
    Trading (Binomo via dados públicos Yahoo). Gera entradas simples:
    - Detecta spike no candle (movimento percentual no último candle)
    - Retorna 1 entrada por scan (a melhor)
    """

    def __init__(self):
        self.thr = {
            "5m": float(getattr(config, "TRADING_SPIKE_PCT_5M", 0.20)),
            "15m": float(getattr(config, "TRADING_SPIKE_PCT_15M", 0.30)),
        }

    async def scan_timeframe(self, yahoo, tickers: List[str], timeframe: str) -> Optional[TradeSignal]:
        if not tickers:
            return None

        now = datetime.now(BR_TZ)
        nxt_dt, nxt_min = _next_slot(now, timeframe)

        best: Optional[TradeSignal] = None
        best_score = -1e9

        for sym in tickers:
            try:
                # precisa existir em YahooData: chart(symbol, interval, limit)
                t, o, h, l, c, v = await yahoo.chart(sym, timeframe, 120)
                if len(c) < 3:
                    continue

                price = float(c[-1])
                prev = float(c[-2])
                if prev <= 0:
                    continue

                chg = ((price - prev) / prev) * 100.0
                abs_chg = abs(chg)

                thr = float(self.thr.get(timeframe, 999.0))
                if abs_chg < thr:
                    continue

                side = "COMPRA" if chg > 0 else "VENDA"
                entry, stop, tp1, tp2, risk_pct, tp1_pct, tp2_pct = _plan(side, price)

                score = abs_chg * 100.0  # bem simples: quanto maior o spike, mais prioridade

                if score > best_score:
                    best_score = score
                    best = TradeSignal(
                        symbol=sym,
                        timeframe=timeframe,
                        side=side,
                        price=price,
                        entry=entry,
                        stop=stop,
                        tp1=tp1,
                        tp2=tp2,
                        risk_pct=risk_pct,
                        tp1_pct=tp1_pct,
                        tp2_pct=tp2_pct,
                        why=f"Movimento do candle {timeframe}: {chg:+.2f}%",
                        next_time_str=nxt_dt.strftime("%H:%M"),
                        next_minute=nxt_min,
                    )
            except Exception:
                continue

        return best

    def build_embed(self, entries: List[TradeSignal], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M BRT")
        binomo_ref = (getattr(config, "BINOMO_REF_LINK", "") or "").strip()

        if not entries:
            # OBS: este embed normalmente não será usado (main não envia se vazio),
            # mas deixo por segurança.
            e = discord.Embed(
                title=f"📉 Binomo Trading — {tier.upper()}",
                description="Faça sua entrada com segurança.",
                color=0x95A5A6,
            )
            if binomo_ref:
                e.add_field(name="✨ Acesso rápido", value=f"🎯 {_masked('Acesse a plataforma e receba benefícios', binomo_ref)}", inline=False)
            e.set_footer(text=f"Atlas v6 • {now}")
            return e

        # se vier mais de uma entrada (investidor), mostra lista
        e = discord.Embed(
            title=f"📈 Binomo Trading — {tier.upper()}",
            description="Faça sua entrada com segurança.",
            color=0x9B59B6,
        )

        lines = []
        for i, s in enumerate(entries, 1):
            arrow = "⬆️" if s.side == "COMPRA" else "⬇️"
            lines.append(
                f"**{i})** {arrow} **{s.side}** • `{s.symbol}` • TF **{s.timeframe}**\n"
                f"Motivo: {s.why}\n"
                f"Preço: **{_fmt_price(s.price)}** | Entrada: **{_fmt_price(s.entry)}**\n"
                f"Stop: {_fmt_price(s.stop)} (**{s.risk_pct:.2f}%**) | "
                f"TP1: {_fmt_price(s.tp1)} (**{s.tp1_pct:.2f}%**) | "
                f"TP2: {_fmt_price(s.tp2)} (**{s.tp2_pct:.2f}%**)\n"
                f"⏱️ Próximo candle: **{s.next_time_str} BRT** (minuto **{s.next_minute:02d}**)"
            )

        e.add_field(name="🎯 Entradas", value="\n\n".join(lines)[:1024], inline=False)

        if binomo_ref:
            e.add_field(
                name="✨ Acesso rápido",
                value=f"🎯 {_masked('Acesse a plataforma e receba benefícios', binomo_ref)}",
                inline=False,
            )

        e.set_footer(text=f"Atlas v6 • {now}")
        return e
