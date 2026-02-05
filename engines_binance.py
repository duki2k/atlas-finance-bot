from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import discord
import pytz
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Pick:
    symbol: str
    price: float
    chg_6h: float
    chg_24h: float
    rsi: float
    trend: str
    score: float
    why: str

def _pct(a: float, b: float) -> float:
    return ((a - b) / b) * 100.0 if b else 0.0

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

class BinanceMentorEngine:
    """
    Mentor educacional 1h:
    - escolhe TOP N moedas com melhor combinação de:
      tendência + força 24h + RSI saudável (evita sobrecompra extrema)
    - reduz spam: pensado para envio 1x/h
    """
    def __init__(self):
        self.top_n = int(getattr(config, "BINANCE_MENTOR_TOP_N", 3) or 3)

    async def scan_1h(self, b, symbols: List[str]) -> List[Pick]:
        out: List[Pick] = []

        for sym in symbols:
            # 1h (precisa pelo menos 30 candles)
            _, _, _, _, c, _ = await b.klines(sym, "1h", 120)
            if len(c) < 40:
                continue

            price = c[-1]
            chg_6h = _pct(c[-1], c[-7])      # ~6h
            chg_24h = _pct(c[-1], c[-25])    # ~24h

            ef = ema(c[-60:], 9)
            es = ema(c[-60:], 21)
            rr = rsi(c[-80:], 14)
            if ef is None or es is None or rr is None:
                continue

            trend_up = ef > es
            trend = "ALTA" if trend_up else "BAIXA"

            # score: tendência + força + RSI "bom"
            score = 0.0
            score += (10.0 if trend_up else -10.0)
            score += (chg_24h * 2.0) + (chg_6h * 1.0)

            # RSI saudável (evita extremos)
            if 45 <= rr <= 70:
                score += 8.0
                rsi_note = "RSI saudável"
            elif rr < 40:
                score += 4.0
                rsi_note = "RSI baixo (cuidado/aguarde confirmação)"
            else:
                score -= 6.0
                rsi_note = "RSI alto (evitar FOMO)"

            why = f"Tendência {trend} (EMA9 vs EMA21), 24h {chg_24h:+.2f}%, 6h {chg_6h:+.2f}%, {rsi_note}."
            out.append(Pick(sym, price, chg_6h, chg_24h, rr, trend, score, why))

        out.sort(key=lambda x: x.score, reverse=True)
        return out[: self.top_n]

    def build_embed(self, picks: List[Pick], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="🧭 Binance Mentor — Recomendações (1h) SPOT",
            description=(
                "Mentoria educacional para **seleção de moedas** no momento.\n"
                "Foco: tendência + força relativa + RSI (sem spam).\n"
                "🧠 Educacional — não é recomendação financeira."
            ),
            color=0x2ECC71,
        )

        if not picks:
            e.add_field(name="📭 Sem candidato forte", value="Nenhuma moeda passou no filtro agora.", inline=False)
        else:
            for i, p in enumerate(picks, start=1):
                badge = "⭐" if i == 1 else "•"
                e.add_field(
                    name=f"{badge} #{i} {p.symbol} ({p.trend})",
                    value=(
                        f"Preço: **{_fmt(p.price)}**\n"
                        f"24h: **{p.chg_24h:+.2f}%** | 6h: **{p.chg_6h:+.2f}%** | RSI: **{p.rsi:.0f}**\n"
                        f"Por quê: {p.why}\n"
                        f"Abordagem: compra **parcelada/DCA** + gestão de risco (sem alavancagem)."
                    ),
                    inline=False,
                )

        link = getattr(config, "BINANCE_REF_LINK", "").strip()
        if link and "COLE_AQUI" not in link:
            e.add_field(name="🔗 Binance (Convite)", value=f"{link}", inline=False)

        e.set_footer(text=f"Atlas Mentor • {tier.upper()} • {now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e
