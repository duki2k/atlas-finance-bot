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
    ticker: str
    interval: str   # "1m"|"5m"|"15m"
    side: str       # "COMPRA"|"VENDA"
    price: float
    why: str
    entry_time: str
    entry_minute: int
    score: float

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1: return f"{p:,.4f}"
    return f"{p:,.6f}"

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 2:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += abs(diff)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def next_slot(now: datetime, interval: str) -> Tuple[datetime, int]:
    now = now.replace(second=0, microsecond=0)
    if interval == "1m":
        nxt = now + timedelta(minutes=1)
        return nxt, nxt.minute
    if interval == "5m":
        m = ((now.minute // 5) + 1) * 5
        if m >= 60:
            nxt = now.replace(minute=0) + timedelta(hours=1)
            return nxt, 0
        nxt = now.replace(minute=m)
        return nxt, m
    m = ((now.minute // 15) + 1) * 15
    if m >= 60:
        nxt = now.replace(minute=0) + timedelta(hours=1)
        return nxt, 0
    nxt = now.replace(minute=m)
    return nxt, m

def is_market_open_for_non_crypto(now_utc: datetime) -> bool:
    # Simples e efetivo: não manda em fim de semana (para forex/indices/commodities)
    wd = now_utc.weekday()  # Mon=0 .. Sun=6
    return wd <= 4

def is_crypto_ticker(ticker: str) -> bool:
    return ticker.endswith("-USD") or ticker.endswith("USDT") or ticker.endswith("BTC")

class BinomoEngine:
    def __init__(self):
        pass

    async def scan_timeframe(self, y, tickers: List[str], interval: str) -> Optional[Entry]:
        now = datetime.now(BR_TZ)
        nxt, nxt_min = next_slot(now, interval)
        best: Optional[Entry] = None

        # Yahoo intervals: 1m/5m/15m ok
        for t in tickers:
            # se não for cripto e mercado fechado, ignora (sem spam)
            now_utc = datetime.utcnow()
            if (not is_crypto_ticker(t)) and (not is_market_open_for_non_crypto(now_utc)):
                continue

            try:
                _, _, _, _, c = await y.chart(t, interval, "1d")
            except Exception:
                continue
            if len(c) < 60:
                continue

            price = c[-1]
            fast = ema(c[-60:], int(config.EMA_FAST))
            slow = ema(c[-60:], int(config.EMA_SLOW))
            r = rsi(c, int(config.RSI_PERIOD))

            if fast is None or slow is None or r is None:
                continue

            # lógica “clara”:
            # COMPRA: RSI baixo + fast>slow (tendência recente a favor)
            # VENDA: RSI alto + fast<slow
            if r <= float(config.RSI_BUY_BELOW) and fast >= slow:
                side = "COMPRA"
                why = f"RSI {r:.0f} (sobrevendido) + tendência (EMA{config.EMA_FAST} ≥ EMA{config.EMA_SLOW})."
                score = (float(config.RSI_BUY_BELOW) - r) + 10
            elif r >= float(config.RSI_SELL_ABOVE) and fast <= slow:
                side = "VENDA"
                why = f"RSI {r:.0f} (sobrecomprado) + fraqueza (EMA{config.EMA_FAST} ≤ EMA{config.EMA_SLOW})."
                score = (r - float(config.RSI_SELL_ABOVE)) + 10
            else:
                continue

            entry = Entry(
                ticker=t,
                interval=interval,
                side=side,
                price=price,
                why=why,
                entry_time=nxt.strftime("%H:%M"),
                entry_minute=nxt_min,
                score=score,
            )

            if best is None or entry.score > best.score:
                best = entry

        return best

    def build_embed(self, entries: List[Entry], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="🟦 Binomo — Entradas (1m/5m/15m)",
            description="Entradas geradas automaticamente com base em dados públicos.\n🧠 Educacional — não é recomendação financeira.",
            color=0x3498DB
        )

        if not entries:
            e.description += "\n\n📭 Nenhuma entrada válida agora."

        for en in entries:
            arrow = "⬆️" if en.side == "COMPRA" else "⬇️"
            e.add_field(
                name=f"{arrow} {en.interval} • {en.ticker}",
                value=(
                    f"Direção: **{en.side}** {arrow}\n"
                    f"Preço: **{_fmt(en.price)}**\n"
                    f"Entrada: **{en.entry_time} BRT** (minuto **{en.entry_minute:02d}**)\n"
                    f"Motivo: {en.why}"
                ),
                inline=False
            )

        if config.BINOMO_REF_LINK and "COLE_AQUI" not in config.BINOMO_REF_LINK:
            e.add_field(
                name="🔗 Binomo (Convite)",
                value=f"[Acessar por aqui]({config.BINOMO_REF_LINK})",
                inline=False
            )

        e.set_footer(text=f"Atlas Radar v4 • {tier.upper()} • {now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, entries: List[Entry], tier: str) -> str:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        lines = [
            f"🟦 Binomo — Entradas (1m/5m/15m) • {tier.upper()}",
            "Educacional — não é recomendação financeira.",
            ""
        ]
        if not entries:
            lines.append("📭 Nenhuma entrada válida agora.")
        else:
            for en in entries:
                arrow = "⬆️" if en.side == "COMPRA" else "⬇️"
                lines.append(f"{arrow} {en.interval} • {en.ticker} • {en.side}")
                lines.append(f"Preço: {_fmt(en.price)}")
                lines.append(f"Entrada: {en.entry_time} BRT (min {en.entry_minute:02d})")
                lines.append(f"Motivo: {en.why}")
                lines.append("")

        if config.BINOMO_REF_LINK and "COLE_AQUI" not in config.BINOMO_REF_LINK:
            lines.append(f"🔗 Binomo (convite): {config.BINOMO_REF_LINK}")

        lines.append("")
        lines.append(f"🕒 {now} BRT")
        return "\n".join(lines)
