from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import pytz
import discord
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")


@dataclass
class MentorPick:
    symbol: str
    price: float
    drop_24h_pct: float
    last_1h_pct: float
    score: float
    why: str


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


class BinanceMentorEngine:
    """
    Binance = Mentor (investimento) — sem entradas.
    Detecta queda 24h relevante (via candles 1h) + sinal de estabilização.
    """

    def __init__(self):
        self.min_drop_24h = float(getattr(config, "BINANCE_MIN_DROP_24H", 2.0))
        self.min_score = float(getattr(config, "BINANCE_MIN_SCORE", 70.0))

    def _score(self, drop_24h: float, last_1h: float, bounce_ok: bool) -> float:
        base = min(abs(drop_24h), 12.0) * 8.0          # 0..96
        rebound = min(max(last_1h, 0.0), 2.0) * 12.0   # 0..24
        stab = 10.0 if bounce_ok else 0.0
        return base + rebound + stab

    async def scan_1h(self, binance, symbols: List[str], top_n: int = 3) -> List[MentorPick]:
        out: List[MentorPick] = []
        if not symbols:
            return out

        for sym in symbols:
            try:
                t, o, h, l, c, v = await binance.klines(sym, "1h", 50)
                if len(c) < 26:
                    continue

                price = float(c[-1])
                c_24h_ago = float(c[-25])
                if c_24h_ago <= 0:
                    continue

                drop_24h_pct = ((price - c_24h_ago) / c_24h_ago) * 100.0
                last_1h_pct = ((c[-1] - c[-2]) / c[-2]) * 100.0 if c[-2] > 0 else 0.0

                # precisa ter caído no mínimo X%
                if drop_24h_pct > -self.min_drop_24h:
                    continue

                # estabilização: candle verde ou sombra inferior relevante
                bounce_ok = (c[-1] > c[-2]) or (c[-1] > float(l[-1]) * 1.003)

                score = self._score(drop_24h_pct, last_1h_pct, bounce_ok)
                if score < self.min_score:
                    continue

                why = f"Queda 24h: **{drop_24h_pct:.2f}%** | Última 1h: **{last_1h_pct:+.2f}%**"
                if bounce_ok:
                    why += " | **estabilização**"

                out.append(MentorPick(
                    symbol=sym,
                    price=price,
                    drop_24h_pct=drop_24h_pct,
                    last_1h_pct=last_1h_pct,
                    score=score,
                    why=why,
                ))
            except Exception:
                continue

        out.sort(key=lambda x: x.score, reverse=True)
        return out[: max(1, int(top_n))]

    def build_embed(self, picks: List[MentorPick], tier: str) -> discord.Embed:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M BRT")
        e = discord.Embed(
            title="🧠 Mentor Binance Spot — Recomendações (1h)",
            description="Foco: **investimento** (sem trading).\n🧠 Educacional — não é recomendação financeira.",
            color=0x3498DB,
        )

        if not picks:
            e.add_field(
                name="📌 Sem pick forte agora",
                value="Nenhuma oportunidade com força suficiente neste ciclo.",
                inline=False,
            )
        else:
            lines = []
            for i, p in enumerate(picks, 1):
                lines.append(
                    f"**{i})** `{p.symbol}` • Preço: **{_fmt_price(p.price)}**\n"
                    f"→ {p.why}\n"
                    f"Score: **{p.score:.0f}**"
                )
            e.add_field(name="💠 Picks", value="\n\n".join(lines)[:1024], inline=False)

        ctas = []
        binance_ref = (getattr(config, "BINANCE_REF_LINK", "") or "").strip()
        discord_inv = (getattr(config, "DISCORD_INVITE_LINK", "") or "").strip()

        if binance_ref:
            ctas.append(f"💠 {_masked('Acesse aqui e comece a investir', binance_ref)}")
        if discord_inv:
            ctas.append(f"🚀 {_masked('Entre no Discord e acompanhe ao vivo', discord_inv)}")

        if ctas:
            e.add_field(name="✨ Acesso rápido", value="\n".join(ctas)[:1024], inline=False)

        e.set_footer(text=f"Atlas v6 • {now}")
        return e
