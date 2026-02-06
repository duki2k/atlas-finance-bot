from __future__ import annotations

import html
import discord
from dataclasses import dataclass
from typing import List


@dataclass
class NewsLine:
    pt: str
    en: str
    source: str


def _esc(s: str) -> str:
    return html.escape((s or "").strip())


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
        binance_link: str = "",
        binomo_link: str = "",
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
        self.binance_link = (binance_link or "").strip()
        self.binomo_link = (binomo_link or "").strip()

    async def run_both(self):
        lines, sources = await self.engine.fetch_lines()
        if not lines:
            await self.logger.info("NEWS: sem itens novos.")
            return

        # dedupe por EN
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

        # Telegram (sempre membro)
        if self.telegram_enabled:
            if not getattr(self.tg, "is_configured", lambda: False)():
                await self.logger.error("NEWS: Telegram ligado mas token/chat_id estão vazios.")
            else:
                txt = self._build_telegram_html(member_pack, sources)
                ok = await self.tg.send_html(txt, disable_preview=True)
                if not ok:
                    err = getattr(self.tg, "last_error", "") or "falha desconhecida"
                    await self.logger.error(f"NEWS: falha Telegram -> {err}")
                else:
                    await self.logger.info("NEWS: Telegram OK (modo membro).")

        await self.logger.info(f"NEWS: ok member={len(member_pack)} invest={len(invest_pack)}")

    def _build_embed(self, pack: List[NewsLine], sources: List[str], tier: str) -> discord.Embed:
        title = f"📰 Atlas Newsletter — Cripto (PT/EN) • {tier}"
        desc = "Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira."
        e = discord.Embed(title=title, description=desc, color=0x3498DB)

        lines = []
        for i, ln in enumerate(pack, 1):
            lines.append(f"**{i}) 🇧🇷** {ln.pt}\n**{i}) 🇺🇸** {ln.en}")
        e.add_field(name="🗞️ Notícias", value="\n\n".join(lines)[:1024], inline=False)

        if sources:
            e.add_field(name="📎 Fontes (referência)", value=", ".join(sorted(set(sources)))[:1024], inline=False)

        # CTAs “encurtadas” (markdown)
        ctas = []
        if self.discord_invite:
            ctas.append(f"🚀 [Entre no Discord ao vivo]({self.discord_invite})")
        if self.binance_link:
            ctas.append(f"💠 [Acesse a Binance aqui]({self.binance_link})")
        if self.binomo_link:
            ctas.append(f"🎯 [Acesse a Binomo aqui]({self.binomo_link})")
        if ctas:
            e.add_field(name="✨ Acesso rápido", value="\n".join(ctas)[:1024], inline=False)

        return e

    def _build_telegram_html(self, pack: List[NewsLine], sources: List[str]) -> str:
        parts = []
        parts.append("📰 <b>Atlas Newsletter — Cripto (PT/EN)</b>")
        parts.append("Texto direto (sem link). Fontes no final apenas para referência.")
        parts.append("🧠 Educacional — não é recomendação financeira.")
        parts.append("")

        for i, ln in enumerate(pack, 1):
            parts.append(f"<b>{i}) 🇧🇷</b> {_esc(ln.pt)}")
            parts.append(f"<b>{i}) 🇺🇸</b> {_esc(ln.en)}")
            parts.append("")

        if sources:
            parts.append("📎 <b>Fontes (referência)</b>")
            parts.append(_esc(", ".join(sorted(set(sources)))))

        # CTAs (links encurtados como texto clicável)
        parts.append("")
        if self.discord_invite:
            parts.append("🚀 <b>Tempo real no Discord</b>")
            parts.append(f'Entre na Atlas Community: <a href="{_esc(self.discord_invite)}">Clique para entrar</a>')
            parts.append("Conteúdo educacional para ajudar você a decidir melhor o que fazer com seu dinheiro.")

        if self.binance_link:
            parts.append(f'💠 Binance: <a href="{_esc(self.binance_link)}">Acesse aqui</a>')

        if self.binomo_link:
            parts.append(f'🎯 Binomo: <a href="{_esc(self.binomo_link)}">Acesse aqui</a>')

        return "\n".join(parts)
