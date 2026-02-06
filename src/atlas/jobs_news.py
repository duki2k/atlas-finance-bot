from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Tuple
import discord


@dataclass
class NewsLine:
    pt: str
    en: str
    source: str


def _clean(s: str) -> str:
    return html.unescape((s or "").strip())


def _to_pt_basic(en: str) -> str:
    """
    Tradução simplificada (sem API) só pra ficar legível em PT.
    Não é perfeita, mas cumpre o requisito "PT/EN" sem serviço pago.
    """
    t = _clean(en)

    repl = {
        " price ": " preço ",
        " prices ": " preços ",
        " surges ": " dispara ",
        " rally ": " rali ",
        " rallies ": " sobe forte ",
        " falls ": " cai ",
        " drops ": " cai ",
        " plunges ": " despenca ",
        " crash ": " desaba ",
        " approval ": " aprovação ",
        " sec ": " sec ",
        " etf ": " etf ",
        " regulation ": " regulação ",
        " lawsuit ": " processo ",
        " exchange ": " exchange ",
        " stablecoin ": " stablecoin ",
        " whales ": " baleias ",
        " miners ": " mineradores ",
        " network ": " rede ",
        " inflows ": " entradas ",
        " outflows ": " saídas ",
        " up ": " alta ",
        " down ": " baixa ",
        " u.s. ": " EUA ",
        " us ": " EUA ",
    }

    low = " " + t + " "
    for a, b in repl.items():
        low = low.replace(a, b)
        low = low.replace(a.title(), b)  # tentativa simples

    out = low.strip()
    # capitalização leve
    if out:
        out = out[0].upper() + out[1:]
    return out


class NewsJob:
    def __init__(
        self,
        state,
        logger,
        notifier,
        tg,
        engine,
        channel_member_id: int,
        channel_invest_id: int,
        max_member: int = 4,
        max_invest: int = 7,
        telegram_enabled: bool = False,
        discord_invite: str = "",
    ):
        self.state = state
        self.logger = logger
        self.notifier = notifier
        self.tg = tg
        self.engine = engine
        self.channel_member_id = int(channel_member_id or 0)
        self.channel_invest_id = int(channel_invest_id or 0)
        self.max_member = int(max_member or 4)
        self.max_invest = int(max_invest or 7)
        self.telegram_enabled = bool(telegram_enabled)
        self.discord_invite = (discord_invite or "").strip()

    async def run_both(self):
        """
        Envia:
        - Discord (membro e investidor)
        - Telegram (sempre modo MEMBRO)
        """
        lines, sources = await self.engine.fetch_lines()

        if not lines:
            await self.logger.info("NEWS: sem itens novos.")
            return

        # Dedup simples por EN
        fresh: List[NewsLine] = []
        for ln in lines:
            key = (ln.en or "").strip().lower()
            if not key:
                continue
            if key in getattr(self.state, "seen_news", set()):
                continue
            getattr(self.state, "seen_news", set()).add(key)
            fresh.append(ln)

        if not fresh:
            await self.logger.info("NEWS: tudo já visto (dedupe).")
            return

        member_pack = fresh[: self.max_member]
        invest_pack = fresh[: self.max_invest]

        # Discord membro
        if self.channel_member_id:
            emb_m = self._build_embed(member_pack, sources, tier="MEMBRO")
            await self.notifier.send_embed(self.channel_member_id, emb_m)

        # Discord investidor
        if self.channel_invest_id:
            emb_i = self._build_embed(invest_pack, sources, tier="INVESTIDOR")
            await self.notifier.send_embed(self.channel_invest_id, emb_i)

        # Telegram: SEMPRE “tipo membro” + CTA
        if self.telegram_enabled:
            txt = self._build_telegram(member_pack, sources)
            await self.tg.send_text(txt)

        await self.logger.info(
            f"NEWS: ok member={len(member_pack)} invest={len(invest_pack)} telegram={'on' if self.telegram_enabled else 'off'}"
        )

    def _build_embed(self, pack: List[NewsLine], sources: List[str], tier: str) -> discord.Embed:
        title = f"📰 Atlas Newsletter — Cripto (PT/EN) • {tier}"
        desc = "Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira."
        e = discord.Embed(title=title, description=desc, color=0x3498DB)

        # leitura espaçada
        lines = []
        for i, ln in enumerate(pack, 1):
            lines.append(f"**{i}) 🇧🇷** {_clean(ln.pt)}\n**{i}) 🇺🇸** {_clean(ln.en)}")
        e.add_field(name="🗞️ Notícias", value="\n\n".join(lines)[:1024], inline=False)

        if sources:
            e.add_field(name="📎 Fontes (referência)", value=", ".join(sorted(set(sources)))[:1024], inline=False)

        if self.discord_invite:
            e.add_field(
                name="🚀 Tempo real no Discord",
                value=f"Entre na Atlas Community para alertas ao vivo: {self.discord_invite}",
                inline=False,
            )
        return e

    def _build_telegram(self, pack: List[NewsLine], sources: List[str]) -> str:
        parts = []
        parts.append("📰 Atlas Newsletter — Cripto (PT/EN)")
        parts.append("Texto direto (sem link). Fontes no final apenas para referência.")
        parts.append("🧠 Educacional — não é recomendação financeira.\n")

        for i, ln in enumerate(pack, 1):
            parts.append(f"{i}) 🇧🇷 {_clean(ln.pt)}")
            parts.append(f"{i}) 🇺🇸 {_clean(ln.en)}")
            parts.append("")  # espaço

        if sources:
            parts.append("📎 Fontes (referência)")
            parts.append(", ".join(sorted(set(sources))))

        # CTA (sem prometer dinheiro garantido)
        if self.discord_invite:
            parts.append("\n🚀 Quer acompanhar alertas e oportunidades em tempo real?")
            parts.append(f"Entre na Atlas Community (Discord): {self.discord_invite}")
            parts.append("Conteúdo educacional para ajudar você a decidir melhor o que fazer com o seu dinheiro.")

        return "\n".join(parts)
