from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Set, Tuple
import re
import html
import os

import discord
import pytz
import feedparser

import config

BR_TZ = pytz.timezone("America/Sao_Paulo")


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
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

    def _feeds_en(self) -> List[Tuple[str, str]]:
        feeds = getattr(config, "NEWS_RSS_FEEDS_EN", None)
        if feeds:
            return list(feeds)
        return list(getattr(config, "NEWS_RSS_FEEDS", []))

    def _max_items(self) -> int:
        if hasattr(config, "NEWS_MAX_ITEMS_EACH"):
            return int(getattr(config, "NEWS_MAX_ITEMS_EACH"))
        return int(getattr(config, "NEWS_MAX_ITEMS", 6))

    def _pick_news_en(self) -> List[NewsItem]:
        out: List[NewsItem] = []
        max_items = self._max_items()

        for source, url in self._feeds_en():
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:10]:
                title = _clean_text((entry.get("title") or "").strip())
                summary = _clean_text((entry.get("summary") or entry.get("description") or "").strip())
                link = (entry.get("link") or "").strip()

                if not title:
                    continue

                key = f"{source}|{link or title}".lower()
                if key in self.seen:
                    continue

                out.append(NewsItem(source=source, title=_short(title, 140), summary=_short(summary, 240)))
                if len(out) >= max_items:
                    return out

        return out

    async def _libre_translate_batch(self, session, texts: List[str], source_lang: str, target_lang: str) -> Tuple[List[str], bool]:
        """
        Usa LibreTranslate se LIBRETRANSLATE_URL estiver configurado.
        Retorna (texts_traduzidos, used=True/False)
        """
        base = (os.getenv("LIBRETRANSLATE_URL") or "").strip()
        if not base:
            return texts, False

        # exemplo: https://seu-libretranslate.railway.app
        url = base.rstrip("/") + "/translate"
        api_key = (os.getenv("LIBRETRANSLATE_API_KEY") or "").strip()  # opcional

        out = []
        used = True

        # faz em lote, mas como o Libre nem sempre aceita “array” padronizado em todas distros,
        # enviamos 1 por 1 com timeout curto (seguro e simples).
        for t in texts:
            payload = {
                "q": t,
                "source": source_lang,
                "target": target_lang,
                "format": "text",
            }
            if api_key:
                payload["api_key"] = api_key
            try:
                async with session.post(url, json=payload, timeout=18) as r:
                    r.raise_for_status()
                    j = await r.json()
                out.append(j.get("translatedText") or t)
            except Exception:
                out.append(t)

        return out, used

    async def fetch(self, session) -> Tuple[List[NewsItem], List[NewsItem], List[str], bool]:
        """
        Retorna:
          pt_items (tradução do EN base)
          en_items (base)
          sources
          translated_ok
        """
        en_items = self._pick_news_en()

        sources = []
        for it in en_items:
            if it.source not in sources:
                sources.append(it.source)

        blocks = []
        for it in en_items:
            blocks.append(f"{it.title} — {it.summary}" if it.summary else it.title)

        pt_blocks, used = await self._libre_translate_batch(session, blocks, "en", "pt")

        pt_items: List[NewsItem] = []
        for i, it in enumerate(en_items):
            txt = pt_blocks[i] if i < len(pt_blocks) else (it.title + (f" — {it.summary}" if it.summary else ""))
            if " — " in txt:
                pt_title, pt_sum = txt.split(" — ", 1)
            else:
                pt_title, pt_sum = txt, ""
            pt_items.append(
                NewsItem(
                    source=it.source,
                    title=_short(_clean_text(pt_title), 140),
                    summary=_short(_clean_text(pt_sum), 240),
                )
            )

        return pt_items, en_items, sources, used

    def mark_seen(self, en_items: List[NewsItem]):
        for it in en_items:
            self.seen.add(f"{it.source}|{it.title}".lower())

    def build_embed(self, pt: List[NewsItem], en: List[NewsItem], sources: List[str], translated_ok: bool) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Atlas Newsletter — Cripto (PT/EN)",
            description="Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.",
            color=0xF1C40F,
        )

        if not en:
            e.add_field(name="🇧🇷 Português", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            pt_blocks = []
            en_blocks = []

            for i in range(len(en)):
                en_it = en[i]
                pt_it = pt[i] if i < len(pt) else None

                en_text = f"{i+1}) **{en_it.title}**"
                if en_it.summary:
                    en_text += f"\n{en_it.summary}"
                en_blocks.append(en_text)

                if pt_it:
                    pt_text = f"{i+1}) **{pt_it.title}**"
                    if pt_it.summary:
                        pt_text += f"\n{pt_it.summary}"
                else:
                    pt_text = en_text
                pt_blocks.append(pt_text)

            e.add_field(name="🇧🇷 Português", value=_short("\n\n".join(pt_blocks), 1024), inline=False)
            e.add_field(name="🇺🇸 English", value=_short("\n\n".join(en_blocks), 1024), inline=False)

            if not translated_ok:
                e.add_field(
                    name="ℹ️ Tradução",
                    value="LIBRETRANSLATE_URL não configurada — PT exibindo o mesmo texto do EN.",
                    inline=False,
                )

        if sources:
            e.add_field(name="📎 Fontes (referência)", value="; ".join(sources), inline=False)

        inv = getattr(config, "DISCORD_INVITE_LINK", "").strip()
        if inv and "COLE_AQUI" not in inv:
            e.add_field(name="🚀 Tempo real no Discord", value=f"Entre na Atlas Community: {inv}", inline=False)

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e
