from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Optional
import html
import re
import feedparser
import pytz
import discord

BR_TZ = pytz.timezone("America/Sao_Paulo")


def clean_text(x: str) -> str:
    if not x:
        return ""
    x = html.unescape(x)
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def short(x: str, n: int) -> str:
    x = (x or "").strip()
    return x if len(x) <= n else x[: n - 1].rstrip() + "…"


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str
    key: str


class NewsroomEngine:
    """
    1A: PT = resumo editorial do MESMO item (sem API, mais profissional).
    EN = título + resumo.
    """
    def __init__(self, feeds_en: List[Tuple[str, str]]):
        self.feeds_en = feeds_en

    def fetch(self, seen: set[str], limit: int = 6) -> Tuple[List[NewsItem], List[str]]:
        items: List[NewsItem] = []
        sources: List[str] = []

        for source, url in self.feeds_en:
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:12]:
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary") or entry.get("description") or "")
                link = (entry.get("link") or "").strip()
                if not title:
                    continue

                key = f"{source}|{link or title}".lower()
                if key in seen:
                    continue

                if source not in sources:
                    sources.append(source)

                items.append(NewsItem(
                    source=source,
                    title=short(title, 140),
                    summary=short(summary, 260),
                    key=key
                ))

                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break

        return items, sources

    def _editorial_pt(self, it: NewsItem) -> str:
        base = it.summary or it.title
        base = short(base, 220)
        return f"Resumo: {base}\nImpacto: atenção ao contexto (volatilidade/fluxo de notícias)."

    def build_embed(self, items: List[NewsItem], sources: List[str], discord_invite: str = "") -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Atlas Newsletter — Cripto (PT/EN)",
            description="Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.",
            color=0xF1C40F,
        )

        if not items:
            e.add_field(name="🇧🇷 Português (Editorial)", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            pt_blocks = []
            en_blocks = []
            for i, it in enumerate(items, start=1):
                en = f"{i}) **{it.title}**"
                if it.summary:
                    en += f"\n{it.summary}"
                en_blocks.append(en)

                pt = f"{i}) **{it.title}**\n{self._editorial_pt(it)}"
                pt_blocks.append(pt)

            e.add_field(name="🇧🇷 Português (Editorial)", value=short("\n\n".join(pt_blocks), 1024), inline=False)
            e.add_field(name="🇺🇸 English", value=short("\n\n".join(en_blocks), 1024), inline=False)

        if sources:
            e.add_field(name="📎 Fontes (referência)", value="; ".join(sources), inline=False)

        if discord_invite:
            e.add_field(name="🚀 Tempo real no Discord", value=f"Entre na Atlas Community: {discord_invite}", inline=False)

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, items: List[NewsItem], sources: List[str], discord_invite: str = "") -> str:
        lines = ["📰 Atlas Newsletter — Cripto (PT/EN)", "Educacional — não é recomendação financeira.", ""]
        if not items:
            lines += ["📭 Sem novidades relevantes neste ciclo.", ""]
        else:
            lines.append("🇧🇷 Português (Editorial)")
            for i, it in enumerate(items, start=1):
                lines.append(f"{i}) {it.title}")
                lines.append(self._editorial_pt(it))
                lines.append("")
            lines.append("🇺🇸 English")
            for i, it in enumerate(items, start=1):
                lines.append(f"{i}) {it.title}")
                if it.summary:
                    lines.append(it.summary)
                lines.append("")

        if sources:
            lines.append("📎 Fontes (referência)")
            lines.append("; ".join(sources))
            lines.append("")

        if discord_invite:
            lines.append("🚀 Tempo real no Discord")
            lines.append(f"Entre na Atlas Community: {discord_invite}")

        return "\n".join(lines)
