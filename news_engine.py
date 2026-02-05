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
    text = html.unescape(text)                 # corrige &#224; etc
    text = re.sub(r"<[^>]+>", " ", text)       # remove HTML tags
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
        # compat: aceita NEWS_RSS_FEEDS_EN ou NEWS_RSS_FEEDS antigo
        feeds = getattr(config, "NEWS_RSS_FEEDS_EN", None)
        if feeds:
            return list(feeds)
        return list(getattr(config, "NEWS_RSS_FEEDS", []))

    def _max_items(self) -> int:
        # compat: NEWS_MAX_ITEMS_EACH / NEWS_MAX_ITEMS
        if hasattr(config, "NEWS_MAX_ITEMS_EACH"):
            return int(getattr(config, "NEWS_MAX_ITEMS_EACH"))
        return int(getattr(config, "NEWS_MAX_ITEMS", 6))

    def _pick_news_en(self) -> List[NewsItem]:
        """Busca EN e retorna uma lista única (base)."""
        out: List[NewsItem] = []
        max_items = self._max_items()

        for source, url in self._feeds_en():
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:10]:
                title = _clean_text((entry.get("title") or "").strip())
                summary = _clean_text((entry.get("summary") or entry.get("description") or "").strip())

                if not title:
                    continue

                # usa link quando disponível pra dedupe melhor; se não, title
                link = (entry.get("link") or "").strip()
                key = f"{source}|{link or title}".lower()
                if key in self.seen:
                    continue

                out.append(
                    NewsItem(
                        source=source,
                        title=_short(title, 140),
                        summary=_short(summary, 240),
                    )
                )

                if len(out) >= max_items:
                    return out

        return out

    async def _deepl_translate_batch(self, session, texts: List[str], target_lang: str) -> List[str]:
        key = (os.getenv("DEEPL_API_KEY") or "").strip()
        if not key:
            # sem key: devolve original
            return texts

        url = (os.getenv("DEEPL_API_URL") or "https://api-free.deepl.com/v2/translate").strip()

        # DeepL aceita múltiplos "text" no form
        data = [("auth_key", key), ("target_lang", target_lang), ("source_lang", "EN")]
        for t in texts:
            data.append(("text", t))

        try:
            async with session.post(url, data=data, timeout=20) as r:
                r.raise_for_status()
                j = await r.json()
            tr = j.get("translations") or []
            out = []
            for i in range(len(texts)):
                out.append((tr[i].get("text") or texts[i]) if i < len(tr) else texts[i])
            return out
        except Exception:
            return texts

    async def fetch(self, session) -> Tuple[List[NewsItem], List[NewsItem], List[str], bool]:
        """
        Retorna:
          pt_items (traduzidos da mesma lista)
          en_items (base)
          sources (nomes)
          translated_ok (True se tinha DEEPL_API_KEY e traduziu)
        """
        en_items = self._pick_news_en()
        sources = []
        for it in en_items:
            if it.source not in sources:
                sources.append(it.source)

        # monta blocos para tradução (title + summary)
        blocks = []
        for it in en_items:
            if it.summary:
                blocks.append(f"{it.title} — {it.summary}")
            else:
                blocks.append(it.title)

        # traduz EN -> PT-BR
        key = (os.getenv("DEEPL_API_KEY") or "").strip()
        translated_ok = bool(key)

        pt_blocks = await self._deepl_translate_batch(session, blocks, target_lang="PT-BR")

        pt_items: List[NewsItem] = []
        for i, it in enumerate(en_items):
            txt = pt_blocks[i] if i < len(pt_blocks) else (it.title + (f" — {it.summary}" if it.summary else ""))
            # tenta separar em title/summary de volta
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

        return pt_items, en_items, sources, translated_ok

    def mark_seen(self, items: List[NewsItem]):
        # marca como vistos por (source|title) porque link não está mais presente aqui
        for it in items:
            self.seen.add(f"{it.source}|{it.title}".lower())

    def build_embed(self, pt: List[NewsItem], en: List[NewsItem], sources: List[str], translated_ok: bool) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Atlas Newsletter — Cripto (PT/EN)",
            description=(
                "Texto direto (sem link). Fontes no final apenas para referência.\n"
                "🧠 Educacional — não é recomendação financeira."
            ),
            color=0xF1C40F,
        )

        if not en:
            e.add_field(name="🇧🇷 Português", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            # ESPAÇAMENTO: 1 item por bloco com linha em branco entre eles
            pt_blocks = []
            en_blocks = []

            for idx in range(len(en)):
                en_it = en[idx]
                pt_it = pt[idx] if idx < len(pt) else None

                # EN
                en_text = f"{idx+1}) **{en_it.title}**"
                if en_it.summary:
                    en_text += f"\n{en_it.summary}"
                en_blocks.append(en_text)

                # PT (mesmo item, traduzido)
                if pt_it:
                    pt_text = f"{idx+1}) **{pt_it.title}**"
                    if pt_it.summary:
                        pt_text += f"\n{pt_it.summary}"
                else:
                    pt_text = f"{idx+1}) **{en_it.title}**"
                    if en_it.summary:
                        pt_text += f"\n{en_it.summary}"
                pt_blocks.append(pt_text)

            pt_val = _short("\n\n".join(pt_blocks), 1024)
            en_val = _short("\n\n".join(en_blocks), 1024)

            e.add_field(name="🇧🇷 Português", value=pt_val, inline=False)
            e.add_field(name="🇺🇸 English", value=en_val, inline=False)

            if not translated_ok:
                e.add_field(
                    name="⚠️ Tradução",
                    value="DEEPL_API_KEY não configurada — PT exibindo o mesmo texto do EN.",
                    inline=False,
                )

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
