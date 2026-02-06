from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Tuple, Union
import feedparser


@dataclass
class RawItem:
    title: str
    source: str


def _clean(s: str) -> str:
    return html.unescape((s or "").strip())


class NewsroomEngine:
    """
    Lê RSS em EN e gera:
    - EN original
    - PT tradução simplificada (sem API paga)
    """

    def __init__(self, feeds_en: List[Union[str, Tuple[str, str]]]):
        self.feeds_en = feeds_en or []

    async def fetch_lines(self):
        """
        Retorna (lines, sources)
        lines: lista de objetos {pt,en,source} (mesma notícia traduzida)
        """
        items: List[RawItem] = []
        sources: List[str] = []

        for it in self.feeds_en:
            # aceita ("Nome", "URL") OU "URL"
            if isinstance(it, (tuple, list)) and len(it) == 2:
                src, url = it[0], it[1]
            else:
                url = str(it)
                src = self._guess_source(url)

            try:
                feed = feedparser.parse(url)
                if getattr(feed, "bozo", False):
                    continue

                sources.append(str(src))
                for entry in (feed.entries or [])[:8]:
                    title = _clean(getattr(entry, "title", ""))
                    if title:
                        items.append(RawItem(title=title, source=str(src)))
            except Exception:
                continue

        # dedupe por título
        seen = set()
        out = []
        for x in items:
            k = x.title.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(x)

        # converte para linhas PT/EN
        lines = []
        for x in out[:12]:
            en = x.title
            pt = self._to_pt_basic(en)
            lines.append(type("NewsLine", (), {"pt": pt, "en": en, "source": x.source})())

        return lines, sources

    def _guess_source(self, url: str) -> str:
        u = (url or "").lower()
        if "coindesk" in u: return "CoinDesk"
        if "cointelegraph" in u: return "Cointelegraph"
        if "cryptoslate" in u: return "CryptoSlate"
        if "cryptopotato" in u: return "CryptoPotato"
        if "thedefiant" in u: return "The Defiant"
        return "RSS"

    def _to_pt_basic(self, en: str) -> str:
        t = _clean(en)
        repl = {
            " price ": " preço ",
            " surges ": " dispara ",
            " rally ": " rali ",
            " rallies ": " sobe forte ",
            " falls ": " cai ",
            " drops ": " cai ",
            " plunges ": " despenca ",
            " crash ": " desaba ",
            " approval ": " aprovação ",
            " regulation ": " regulação ",
            " lawsuit ": " processo ",
            " exchange ": " exchange ",
            " stablecoin ": " stablecoin ",
            " whales ": " baleias ",
            " miners ": " mineradores ",
            " network ": " rede ",
            " inflows ": " entradas ",
            " outflows ": " saídas ",
            " u.s. ": " EUA ",
            " us ": " EUA ",
        }
        low = " " + t + " "
        for a, b in repl.items():
            low = low.replace(a, b)
            low = low.replace(a.title(), b)
        out = low.strip()
        if out:
            out = out[0].upper() + out[1:]
        return out
