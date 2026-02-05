from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Set
import discord
import pytz
import feedparser
import config

BR_TZ = pytz.timezone("America/Sao_Paulo")

@dataclass
class NewsItem:
    source: str
    title: str
    link: str

class NewsEngine:
    def __init__(self):
        self.seen: Set[str] = set()

    def fetch(self) -> List[NewsItem]:
        items: List[NewsItem] = []
        for source, url in config.NEWS_RSS_FEEDS:
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:10]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                key = f"{source}|{link}"
                if key in self.seen:
                    continue
                items.append(NewsItem(source=source, title=title, link=link))
        # ordena “novos primeiro” (best-effort)
        return items[: int(config.NEWS_MAX_ITEMS)]

    def mark_seen(self, items: List[NewsItem]):
        for it in items:
            self.seen.add(f"{it.source}|{it.link}")

    def build_embed(self, items: List[NewsItem]) -> discord.Embed:
        now = datetime.now(BR_TZ)
        title = "📰 Cripto News — Atlas Newsletter"
        desc = "Resumo sério do mundo cripto com **fontes**.\n"

        if not items:
            desc += "\n📭 Sem novidades relevantes neste ciclo."

        e = discord.Embed(title=title, description=desc, color=0xF1C40F)

        if items:
            lines = []
            for it in items:
                lines.append(f"• **{it.source}** — [{it.title}]({it.link})")
            e.add_field(name="📌 Destaques", value="\n".join(lines)[:1024], inline=False)

        # Gancho Discord
        if config.DISCORD_INVITE_LINK and "COLE_AQUI" not in config.DISCORD_INVITE_LINK:
            e.add_field(
                name="🚀 Acompanhe em tempo real",
                value=f"Entre no Discord da **Atlas Community**: {config.DISCORD_INVITE_LINK}",
                inline=False
            )

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e

    def build_telegram(self, items: List[NewsItem]) -> str:
        now = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
        lines = ["📰 *Cripto News — Atlas Newsletter*", ""]
        if not items:
            lines.append("📭 Sem novidades relevantes neste ciclo.")
        else:
            for it in items:
                lines.append(f"• {it.source}: {it.title}")
                lines.append(it.link)
                lines.append("")

        # Gancho
        if config.DISCORD_INVITE_LINK and "COLE_AQUI" not in config.DISCORD_INVITE_LINK:
            lines.append("🚀 Quer acompanhar em tempo real as movimentações e alertas?")
            lines.append(f"Entra no Discord da Atlas Community: {config.DISCORD_INVITE_LINK}")

        lines.append("")
        lines.append(f"🕒 {now} BRT")
        return "\n".join(lines)
