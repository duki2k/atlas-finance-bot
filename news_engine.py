from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Set, Tuple
import re
import discord
import pytz
import feedparser
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"

@dataclass
class NewsItem:
    source: str
    title: str
    summary: str

class NewsEngine:
    def __init__(self):
        self.seen: Set[str] = set()

    def _fetch_from(self, feeds: List[Tuple[str, str]], limit_each: int) -> List[NewsItem]:
        out: List[NewsItem] = []
        for source, url in feeds:
            d = feedparser.parse(url)
            for entry in (d.entries or [])[: max(10, limit_each * 2)]:
                title = _strip_html((entry.get("title") or "").strip())
                summary = _strip_html((entry.get("summary") or entry.get("description") or "").strip())
                if not title:
                    continue

                key = f"{source}|{title}".lower()
                if key in self.seen:
                    continue

                out.append(NewsItem(source=source, title=title, summary=_short(summary, 220)))
                if len(out) >= limit_each:
                    break
        return out

    def fetch(self) -> Tuple[List[NewsItem], List[NewsItem]]:
        pt = self._fetch_from(list(getattr(config, "NEWS_RSS_FEEDS_PT", [])), int(getattr(config, "NEWS_MAX_ITEMS_EACH", 4)))
        en = self._fetch_from(list(getattr(config, "NEWS_RSS_FEEDS_EN", [])), int(getattr(config, "NEWS_MAX_ITEMS_EACH", 4)))
        return pt, en

    def mark_seen(self, items: List[NewsItem]):
        for it in items:
            self.seen.add(f"{it.source}|{it.title}".lower())

    def build_embed(self, pt: List[NewsItem], en: List[NewsItem]) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Atlas Newsletter — Cripto (PT/EN)",
            description="Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.",
            color=0xF1C40F,
        )

        if not pt:
            e.add_field(name="🇧🇷 Português", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
        else:
            lines = []
            for i, it in enumerate(pt, 1):
                s = f"{i}) {it.title}"
                if it.summary:
                    s += f" — {it.summary}"
                lines.append(s)
            e.add_field(name="🇧🇷 Português", value=_short("\n".join(lines), 1024), inline=False)

        if not en:
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            lines = []
            for i, it in enumerate(en, 1):
                s = f"{i}) {it.title}"
                if it.summary:
                    s += f" — {it.summary}"
                lines.append(s)
            e.add_field(name="🇺🇸 English", value=_short("\n".join(lines), 1024), inline=False)

        sources = []
        for it in (pt + en):
            if it.source not in sources:
                sources.append(it.source)
        if sources:
            e.add_field(name="📎 Fontes (referência)", value="; ".join(sources), inline=False)

        inv = getattr(config, "DISCORD_INVITE_LINK", "").strip()
        if inv and "COLE_AQUI" not in inv:
            e.add_field(
                name="🚀 Tempo real no Discord",
                value=f"Entre na Atlas Community para alertas ao vivo: {inv}",
                inline=False,
            )

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e
