# radar.py (Atlas Radar v3 - SPOT)
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math
import pytz
import discord

import config
from binance_spot import BinanceSpot
from notifier import Notifier

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class Alert:
    kind: str
    symbol: str
    direction: str  # "COMPRA" ou "VENDA" (spot venda = reduzir/realizar/proteger)
    price: float
    change_pct: float
    volume_mult: Optional[float]
    level: Optional[float]
    entry_minute: int
    entry_time_str: str
    why: str
    playbook: str
    score: float

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:,.6f}"

def _next_slot(now: datetime, step_minutes: int) -> Tuple[datetime, int]:
    minute = now.minute
    next_min = ((minute // step_minutes) + 1) * step_minutes
    base = now.replace(second=0, microsecond=0)
    if next_min >= 60:
        base = base.replace(minute=0) + timedelta(hours=1)
        return base, 0
    return base.replace(minute=next_min), next_min

def _vol_mult(vols: List[float], lookback: int = 20) -> Optional[float]:
    if len(vols) < lookback + 2:
        return None
    v_now = vols[-1]
    base = vols[-(lookback+1):-1]
    avg = sum(base) / len(base) if base else 0.0
    if avg <= 0:
        return None
    return v_now / avg

def _cooldown_key(a: Alert) -> Tuple[str, str]:
    return (a.kind, a.symbol)

class RadarEngine:
    def __init__(self):
        self.last_sent: Dict[Tuple[str, str], float] = {}
        self.paused_until_ts: float = 0.0
        self.last_cycle_brt: str = ""

    def paused(self) -> bool:
        return (datetime.now(BR_TZ).timestamp() < self.paused_until_ts)

    def pause_minutes(self, minutes: int):
        self.paused_until_ts = (datetime.now(BR_TZ) + timedelta(minutes=minutes)).timestamp()

    def resume(self):
        self.paused_until_ts = 0.0

    def _can_send(self, alert: Alert) -> bool:
        cd = int(config.COOLDOWN_MINUTES.get(alert.kind, 30))
        key = _cooldown_key(alert)
        now_ts = datetime.now(BR_TZ).timestamp()
        last = self.last_sent.get(key, 0.0)
        if (now_ts - last) < (cd * 60):
            return False
        self.last_sent[key] = now_ts
        return True

    def _score(self, kind: str, abs_pct: float, vol_mult: Optional[float]) -> float:
        base = {"SPIKE_5M": 70, "BREAKOUT_15M": 85, "BREAKDOWN_15M": 85, "EMA_CROSS_15M": 60}.get(kind, 50)
        s = base + min(abs_pct, 5.0) * 8.0
        if vol_mult is not None:
            s += min(vol_mult, 3.0) * 10.0
        return s

    def _playbook(self, kind: str, direction: str) -> str:
        # ✅ “o que fazer com o dinheiro” em formato de playbook (educacional)
        if direction == "COMPRA":
            return (
                "✅ **Playbook (educacional):**\n"
                "• Se você é investidor: evite FOMO; prefira **compras parceladas (DCA)**.\n"
                "• Se você é trader: espere **confirmação/fechamento** e defina **stop**.\n"
                "• Regra de risco: arrisque pouco por operação (ex.: **0.5%–1%** do capital)."
            )
        return (
            "🛡️ **Playbook (educacional):**\n"
            "• Em SPOT, **VENDA** geralmente = realizar lucro, reduzir exposição ou proteger caixa.\n"
            "• Evite “comprar queda” no impulso; espere estrutura voltar.\n"
            "• Se você tem posição: considere stops/realização parcial e rebalanceamento."
        )

    async def generate_alerts(self, b: BinanceSpot) -> List[Alert]:
        now = datetime.now(BR_TZ)
        alerts: List[Alert] = []

        wl = list(getattr(config, "WATCHLIST", []))
        if not wl:
            return []

        # compute entry times
        slot15_dt, slot15_min = _next_slot(now, 15)
        slot05_dt, slot05_min = _next_slot(now, 5)

        for sym in wl:
            # --- 5m spike from 1m klines (last 6 closes = 5 minutes delta)
            t1, o1, h1, l1, c1, v1 = await b.klines(sym, "1m", 10)
            if len(c1) >= 6:
                prev = c1[-6]
                last = c1[-1]
                if prev > 0:
                    chg5 = ((last - prev) / prev) * 100.0
                    thr = float(config.SPIKE_5M_PCT.get(sym, config.SPIKE_5M_DEFAULT_PCT))
                    if abs(chg5) >= thr:
                        direction = "COMPRA" if chg5 > 0 else "VENDA"
                        score = self._score("SPIKE_5M", abs(chg5), None)
                        alerts.append(Alert(
                            kind="SPIKE_5M",
                            symbol=sym,
                            direction=direction,
                            price=last,
                            change_pct=chg5,
                            volume_mult=None,
                            level=None,
                            entry_minute=slot05_min,
                            entry_time_str=slot05_dt.strftime("%H:%M"),
                            why=f"Movimento rápido em **5m**: {chg5:+.2f}%",
                            playbook=self._playbook("SPIKE_5M", direction),
                            score=score,
                        ))

            # --- 15m breakout/breakdown + EMA cross
            t15, o15, h15, l15, c15, v15 = await b.klines(sym, "15m", 80)
            if len(c15) < 30:
                continue

            last = c15[-1]
            prev = c15[-2]
            chg15 = ((last - prev) / prev) * 100.0 if prev > 0 else 0.0
            vm = _vol_mult(v15, lookback=int(config.BREAK_15M_LOOKBACK))

            # levels
            lb = int(config.BREAK_15M_LOOKBACK)
            if len(h15) >= lb + 2 and len(l15) >= lb + 2:
                hi = max(h15[-(lb+1):-1])
                lo = min(l15[-(lb+1):-1])

                if last > hi and (vm is None or vm >= float(config.BREAK_15M_VOL_MULT)):
                    direction = "COMPRA"
                    score = self._score("BREAKOUT_15M", abs(chg15), vm)
                    alerts.append(Alert(
                        kind="BREAKOUT_15M",
                        symbol=sym,
                        direction=direction,
                        price=last,
                        change_pct=chg15,
                        volume_mult=vm,
                        level=hi,
                        entry_minute=slot15_min,
                        entry_time_str=slot15_dt.strftime("%H:%M"),
                        why=f"Breakout **15m** acima da máxima {lb}c + volume.",
                        playbook=self._playbook("BREAKOUT_15M", direction),
                        score=score,
                    ))

                if last < lo and (vm is None or vm >= float(config.BREAK_15M_VOL_MULT)):
                    direction = "VENDA"
                    score = self._score("BREAKDOWN_15M", abs(chg15), vm)
                    alerts.append(Alert(
                        kind="BREAKDOWN_15M",
                        symbol=sym,
                        direction=direction,
                        price=last,
                        change_pct=chg15,
                        volume_mult=vm,
                        level=lo,
                        entry_minute=slot15_min,
                        entry_time_str=slot15_dt.strftime("%H:%M"),
                        why=f"Breakdown **15m** abaixo da mínima {lb}c + volume.",
                        playbook=self._playbook("BREAKDOWN_15M", direction),
                        score=score,
                    ))

            # EMA cross 15m
            fast = ema(c15[-60:], int(config.EMA_FAST))
            slow = ema(c15[-60:], int(config.EMA_SLOW))
            fast_prev = ema(c15[-61:-1], int(config.EMA_FAST)) if len(c15) >= 61 else None
            slow_prev = ema(c15[-61:-1], int(config.EMA_SLOW)) if len(c15) >= 61 else None

            if None not in (fast, slow, fast_prev, slow_prev):
                if fast_prev <= slow_prev and fast > slow:
                    direction = "COMPRA"
                    score = self._score("EMA_CROSS_15M", abs(chg15), vm)
                    alerts.append(Alert(
                        kind="EMA_CROSS_15M",
                        symbol=sym,
                        direction=direction,
                        price=last,
                        change_pct=chg15,
                        volume_mult=vm,
                        level=None,
                        entry_minute=slot15_min,
                        entry_time_str=slot15_dt.strftime("%H:%M"),
                        why="Cruzamento de tendência **15m** (EMA9 ↑ EMA21).",
                        playbook=self._playbook("EMA_CROSS_15M", direction),
                        score=score,
                    ))
                elif fast_prev >= slow_prev and fast < slow:
                    # em SPOT isso vira alerta de proteção/realização (VENDA)
                    direction = "VENDA"
                    score = self._score("EMA_CROSS_15M", abs(chg15), vm)
                    alerts.append(Alert(
                        kind="EMA_CROSS_15M",
                        symbol=sym,
                        direction=direction,
                        price=last,
                        change_pct=chg15,
                        volume_mult=vm,
                        level=None,
                        entry_minute=slot15_min,
                        entry_time_str=slot15_dt.strftime("%H:%M"),
                        why="Cruzamento de tendência **15m** (EMA9 ↓ EMA21).",
                        playbook=self._playbook("EMA_CROSS_15M", direction),
                        score=score,
                    ))

        # escolhe os melhores do ciclo (profissional = menos ruído)
        alerts.sort(key=lambda a: a.score, reverse=True)
        return alerts[: int(config.MAX_ALERTS_PER_CYCLE)]

    def build_embed(self, a: Alert) -> discord.Embed:
        color = 0x2ECC71 if a.direction == "COMPRA" else 0xE74C3C
        title = f"🚨 Atlas Radar — {a.direction} (SPOT)"
        desc = (
            f"**Ativo:** `{a.symbol}`\n"
            f"**Motivo:** {a.why}\n\n"
            "🧠 Educacional — não é recomendação financeira."
        )
        e = discord.Embed(title=title, description=desc, color=color)
        e.add_field(name="💲 Preço", value=_fmt_price(a.price), inline=True)
        e.add_field(name="📈 Variação", value=f"{a.change_pct:+.2f}% (15m)", inline=True)

        if a.level is not None:
            e.add_field(name="🎯 Nível", value=_fmt_price(a.level), inline=True)

        vm = f"{a.volume_mult:.2f}x" if a.volume_mult is not None else "—"
        e.add_field(name="📊 Volume", value=vm, inline=True)

        e.add_field(
            name="⏱️ Minuto de entrada",
            value=f"Próxima confirmação em **{a.entry_time_str} BRT** (minuto **{a.entry_minute:02d}**).",
            inline=False,
        )
        e.add_field(name="🧭 O que fazer", value=a.playbook, inline=False)
        e.set_footer(text=f"Atlas Radar • {datetime.now(BR_TZ).strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram_text(self, a: Alert) -> str:
        vm = f"{a.volume_mult:.2f}x" if a.volume_mult is not None else "-"
        level = _fmt_price(a.level) if a.level is not None else "-"
        return (
            f"🚨 Atlas Radar (SPOT) — {a.direction}\n"
            f"Ativo: {a.symbol}\n"
            f"Preço: {_fmt_price(a.price)}\n"
            f"Variação (15m): {a.change_pct:+.2f}%\n"
            f"Nível: {level}\n"
            f"Volume: {vm}\n"
            f"Motivo: {a.why}\n"
            f"Entrada: próxima confirmação {a.entry_time_str} BRT (min {a.entry_minute:02d})\n\n"
            f"{a.playbook}\n\n"
            "Educacional — não é recomendação financeira."
        )

    async def run_cycle(self, b: BinanceSpot, n: Notifier, force: bool = False) -> Tuple[int, int]:
        if not getattr(config, "RADAR_ENABLED", False):
            return (0, 0)
        if self.paused() and not force:
            return (0, 0)

        alerts = await self.generate_alerts(b)
        sent = 0

        for a in alerts:
            if force or self._can_send(a):
                emb = self.build_embed(a)
                await n.send_discord_alert(emb)
                await n.send_telegram(self.build_telegram_text(a))
                sent += 1

        return (sent, len(alerts))
