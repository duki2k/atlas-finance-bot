from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import discord
from datetime import datetime
import pytz
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Pick:
    symbol: str
    price: float
    chg24: float
    mom1h: float
    why: str
    score: float

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1: return f"{p:,.4f}"
    return f"{p:,.6f}"

class BinanceMentorEngine:
    async def scan(self, binance, symbols: List[str]) -> Optional[Pick]:
        best: Optional[Pick] = None

        for sym in symbols:
            try:
                t24 = await binance.ticker24h(sym)
                chg24 = float(t24.get("priceChangePercent") or 0.0)
                price, mom1h = await binance.last_close_and_momentum(sym)

                # Queremos: queda 24h (oportunidade) + retomada/momento 1h (não “pegar faca”)
                dip = max(0.0, -chg24)
                mom = max(0.0, mom1h)

                score = (dip * 10.0) + (mom * 6.0)

                if dip < 0.7:  # pouco dip → geralmente não vale “mentor”
                    continue

                why = f"Queda 24h: {chg24:+.2f}% • Momento 1h: {mom1h:+.2f}%"
                p = Pick(sym, price, chg24, mom1h, why, score)

                if best is None or p.score > best.score:
                    best = p
            except Exception:
                continue

        return best

    def build_embed(self, pick: Optional[Pick], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        ref = str(getattr(config, "BINANCE_REF_LINK", "") or "").strip()

        if not pick:
            e = discord.Embed(
                title="🧠 Mentor Binance Spot — Sem pick forte agora",
                description="Nenhuma oportunidade com força suficiente neste ciclo.\n🧠 Educacional — não é recomendação financeira.",
                color=0x95A5A6,
            )
            if ref:
                e.add_field(name="🔗 Conta Binance (indicação)", value=ref, inline=False)
            e.set_footer(text=f"Atlas v6 • {now} BRT")
            return e

        e = discord.Embed(
            title=f"🧠 Mentor Binance Spot — {tier.upper()}",
            description="Recomendação educacional de **1 ativo** para acompanhar/avaliar compra spot.\n🧠 Educacional — não é recomendação financeira.",
            color=0x3498DB,
        )
        e.add_field(name="Ativo", value=f"`{pick.symbol}`", inline=True)
        e.add_field(name="Preço", value=_fmt(pick.price), inline=True)
        e.add_field(name="Contexto", value=pick.why, inline=False)

        e.add_field(
            name="Plano (educacional)",
            value="Ideia: procurar entrada em pullback/estabilização no gráfico de 1h.\nEvite comprar “no meio” de uma queda forte sem sinal de retomada.",
            inline=False,
        )

        if ref:
            e.add_field(name="🔗 Conta Binance (indicação)", value=ref, inline=False)

        e.set_footer(text=f"Atlas v6 • {now} BRT")
        return e
