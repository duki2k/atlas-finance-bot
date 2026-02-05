from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
import discord
import pytz
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Dip:
    symbol: str
    price: float
    chg_15m: float
    chg_1h: float
    score: float

def _pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return ((a - b) / b) * 100.0

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1: return f"{p:,.4f}"
    return f"{p:,.6f}"

class BinanceDipEngine:
    def __init__(self):
        pass

    async def scan(self, b, symbols: List[str]) -> List[Dip]:
        out: List[Dip] = []
        for sym in symbols:
            _, _, _, _, c, _ = await b.klines(sym, "15m", 8)  # 2h
            if len(c) < 5:
                continue
            price = c[-1]
            chg15 = _pct(c[-1], c[-2])
            chg1h = _pct(c[-1], c[-5])  # 1h (4 candles 15m)

            if chg15 <= config.BINANCE_DIP_15M or chg1h <= config.BINANCE_DIP_1H:
                score = abs(chg15) * 2 + abs(chg1h)
                out.append(Dip(sym, price, chg15, chg1h, score))

        out.sort(key=lambda x: x.score, reverse=True)
        return out[: int(config.BINANCE_TOP_N)]

    def build_embed(self, dips: List[Dip], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ)
        title = "🟩 Binance SPOT — Possíveis compras (queda)"
        desc = (
            "Monitoramento automático de **moedas em queda** para achar possíveis pontos de compra spot.\n"
            "🧠 Educacional — não é recomendação financeira.\n\n"
        )

        if not dips:
            desc += "📭 Nenhuma queda relevante agora (sem setup)."

        e = discord.Embed(title=title, description=desc, color=0x2ECC71)

        for d in dips:
            e.add_field(
                name=f"⬇️ {d.symbol}",
                value=(
                    f"Preço: **{_fmt(d.price)}**\n"
                    f"15m: **{d.chg_15m:+.2f}%** | 1h: **{d.chg_1h:+.2f}%**\n"
                    f"Ação: ✅ *Possível compra spot* (aguarde confirmação)"
                ),
                inline=False,
            )

        # Link de afiliado sempre presente
        if config.BINANCE_REF_LINK and "COLE_AQUI" not in config.BINANCE_REF_LINK:
            e.add_field(
                name="🔗 Binance (Convite)",
                value=f"[Abrir Binance por aqui]({config.BINANCE_REF_LINK})",
                inline=False,
            )

        e.set_footer(text=f"Atlas Radar v4 • {tier.upper()} • {now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, dips: List[Dip], tier: str) -> str:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        lines = [
            f"🟩 Binance SPOT — Possíveis compras (queda) • {tier.upper()}",
            "Educacional — não é recomendação financeira.",
            ""
        ]
        if not dips:
            lines.append("📭 Nenhuma queda relevante agora.")
        else:
            for d in dips:
                lines.append(f"⬇️ {d.symbol} | preço {d.price:.6g} | 15m {d.chg_15m:+.2f}% | 1h {d.chg_1h:+.2f}%")
                lines.append("✅ Possível compra spot (aguarde confirmação)")
                lines.append("")

        if config.BINANCE_REF_LINK and "COLE_AQUI" not in config.BINANCE_REF_LINK:
            lines.append(f"🔗 Binance (convite): {config.BINANCE_REF_LINK}")

        lines.append("")
        lines.append(f"🕒 {now} BRT")
        return "\n".join(lines)
