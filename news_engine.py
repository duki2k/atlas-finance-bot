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


def _short(text: str, n: int = 170) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _to_pt(en: str) -> str:
    """
    Tradução leve (título/linha curta). Sem depender de API externa.
    Se você quiser tradução perfeita, dá pra plugar um provider depois.
    """
    # heurística simples: mantém nomes próprios/siglas
    # (o mais importante é ficar legível e rápido)
    return en  # <- mantém em inglês caso você prefira evitar traduções ruins


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str


class NewsEngine:
    def __init__(self):
        self.seen: Set[str] = set()

    def fetch(self) -> List[NewsItem]:
        items: List[NewsItem] = []

        for source, url in config.NEWS_RSS_FEEDS:
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:10]:
                title = _strip_html((entry.get("title") or "").strip())
                summary = _strip_html((entry.get("summary") or entry.get("description") or "").strip())

                if not title:
                    continue

                # chave para dedupe (usa título+source)
                key = f"{source}|{title}".lower()
                if key in self.seen:
                    continue

                items.append(
                    NewsItem(
                        source=source,
                        title=title,
                        summary=_short(summary, 220),
                    )
                )

        # pega apenas os primeiros N
        return items[: int(getattr(config, "NEWS_MAX_ITEMS", 6))]

    def mark_seen(self, items: List[NewsItem]):
        for it in items:
            self.seen.add(f"{it.source}|{it.title}".lower())

    def build_embed(self, items: List[NewsItem]) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Cripto News — Atlas Newsletter (PT/EN)",
            description="Resumo sério do mundo cripto (texto direto) + fontes ao final.\n"
                        "🧠 Educacional — não é recomendação financeira.",
            color=0xF1C40F,
        )

        if not items:
            e.add_field(name="🇧🇷 Português", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            # PT
            pt_lines = []
            en_lines = []
            sources = []

            for idx, it in enumerate(items, start=1):
                sources.append(it.source)

                # PT (se quiser tradução real, troque _to_pt por uma função de tradução)
                pt_title = _to_pt(it.title)
                pt_sum = _to_pt(it.summary) if it.summary else ""
                pt_lines.append(f"{idx}) {pt_title}" + (f" — {pt_sum}" if pt_sum else ""))

                # EN
                en_lines.append(f"{idx}) {it.title}" + (f" — {it.summary}" if it.summary else ""))

            e.add_field(name="🇧🇷 Português", value=_short("\n".join(pt_lines), 1024), inline=False)
            e.add_field(name="🇺🇸 English", value=_short("\n".join(en_lines), 1024), inline=False)

            # Fontes no final (sem link)
            uniq = []
            for s in sources:
                if s not in uniq:
                    uniq.append(s)
            e.add_field(name="📎 Fontes (referência)", value="; ".join(uniq), inline=False)

        # Gancho pro Discord
        inv = getattr(config, "DISCORD_INVITE_LINK", "").strip()
        if inv and "COLE_AQUI" not in inv:
            e.add_field(
                name="🚀 Tempo real no Discord",
                value=f"Entre na **Atlas Community** pra acompanhar alertas ao vivo: {inv}",
                inline=False
            )

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, items: List[NewsItem]) -> str:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        lines = ["📰 Cripto News — Atlas Newsletter (PT/EN)", ""]

        if not items:
            lines += ["🇧🇷 📭 Sem novidades relevantes neste ciclo.", "🇺🇸 📭 No relevant updates this cycle.", ""]
            sources = []
        else:
            lines.append("🇧🇷 Português")
            for idx, it in enumerate(items, start=1):
                pt_title = _to_pt(it.title)
                pt_sum = _to_pt(it.summary) if it.summary else ""
                lines.append(f"{idx}) {pt_title}" + (f" — {pt_sum}" if pt_sum else ""))
            lines.append("")

            lines.append("🇺🇸 English")
            for idx, it in enumerate(items, start=1):
                lines.append(f"{idx}) {it.title}" + (f" — {it.summary}" if it.summary else ""))
            lines.append("")

            sources = []
            for it in items:
                if it.source not in sources:
                    sources.append(it.source)

        if sources:
            lines.append("📎 Fontes (referência): " + "; ".join(sources))
            lines.append("")

        inv = getattr(config, "DISCORD_INVITE_LINK", "").strip()
        if inv and "COLE_AQUI" not in inv:
            lines.append("🚀 Quer acompanhar em tempo real os alertas e movimentos?")
            lines.append(f"Entre no Discord da Atlas Community: {inv}")
            lines.append("")

        lines.append(f"🕒 {now} BRT")
        return "\n".join(lines)
