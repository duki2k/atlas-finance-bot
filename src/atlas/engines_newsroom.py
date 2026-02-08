from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from typing import List, Tuple, Union, Optional

import feedparser
import config


@dataclass
class NewsLine:
    pt: str
    en: str
    source: str


def _clean(s: str) -> str:
    return html.unescape((s or "").strip())


def _pt_headline(en: str) -> str:
    """
    Tradutor offline (sem API) focado em TÍTULOS.
    Não é perfeito, mas melhora bastante a legibilidade sem depender de serviço externo.
    """
    t = _clean(en)

    patterns = [
        (r"^(?P<who>.+?) shares jump (?P<pct>\d+)% after (?P<why>.+)$",
         lambda d: f"Ações da {d['who']} sobem {d['pct']}% após {d['why']}"),
        (r"^(?P<who>.+?) jumps (?P<pct>\d+)% after (?P<why>.+)$",
         lambda d: f"{d['who']} sobe {d['pct']}% após {d['why']}"),
        (r"^(?P<who>.+?) rockets (?P<pct>\d+)%.*$",
         lambda d: f"{d['who']} dispara {d['pct']}%"),
        (r"^(?P<who>.+?) tumbles below (?P<lvl>[\$€£]?\d[\d,\.]+).*$",
         lambda d: f"{d['who']} cai e fica abaixo de {d['lvl']}"),
        (r"^(?P<who>.+?) falls to (?P<lvl>[\$€£]?\d[\d,\.]+).*$",
         lambda d: f"{d['who']} cai para {d['lvl']}"),
        (r"^Three signs that (?P<who>.+?) price could be near (?P<why>.+)$",
         lambda d: f"Três sinais de que o preço de {d['who']} pode estar perto de {d['why']}"),
        (r"^(?P<who>.+?) is under fire after (?P<why>.+)$",
         lambda d: f"{d['who']} fica sob pressão após {d['why']}"),
        (r"^(?P<who>.+?) prepares to (?P<do>.+)$",
         lambda d: f"{d['who']} se prepara para {d['do']}"),
        (r"^(?P<who>.+?) to exit (?P<where>.+?), reduce staff by (?P<pct>\d+)%.*$",
         lambda d: f"{d['who']} vai sair de {d['where']} e reduzir equipe em {d['pct']}%"),
    ]

    for rx, fn in patterns:
        m = re.match(rx, t, flags=re.IGNORECASE)
        if m:
            out = fn(m.groupdict())
            return (out[0].upper() + out[1:]) if out else t

    dict_map = {
        "shares": "ações",
        "jump": "sobem",
        "jumps": "sobe",
        "rocket": "dispara",
        "rockets": "dispara",
        "falls": "cai",
        "drops": "cai",
        "plunges": "despenca",
        "market": "mercado",
        "under fire": "sob pressão",
        "retirement funds": "fundos de aposentadoria",
        "brutal": "forte",
        "trend": "tendência",
        "regulation": "regulação",
        "lawsuit": "processo",
        "exchange": "exchange",
        "stablecoin": "stablecoin",
        "whales": "baleias",
        "miners": "mineradores",
        "network": "rede",
        "inflows": "entradas",
        "outflows": "saídas",
        "U.S.": "EUA",
        "U.K.": "Reino Unido",
        "EU": "União Europeia",
        "crypto": "cripto",
    }

    out = t
    for a, b in dict_map.items():
        out = re.sub(rf"\b{re.escape(a)}\b", b, out, flags=re.IGNORECASE)

    return (out[0].upper() + out[1:]) if out else out


class NewsroomEngine:
    """
    Engine de notícias:
    - Aceita feeds via argumento OU pega do config.NEWS_RSS_FEEDS_EN
    - fetch_lines() aceita (session opcional) e (limit opcional) e ignora kwargs extras
    - Compatível com chamadas antigas e novas
    """

    def __init__(self, feeds_en: Optional[List[Union[str, Tuple[str, str]]]] = None):
        if feeds_en is None:
            feeds_en = getattr(config, "NEWS_RSS_FEEDS_EN", [])
        self.feeds_en = feeds_en or []

    def _guess_source(self, url: str) -> str:
        u = (url or "").lower()
        if "coindesk" in u: return "CoinDesk"
        if "cointelegraph" in u: return "Cointelegraph"
        if "cryptoslate" in u: return "CryptoSlate"
        if "cryptopotato" in u: return "CryptoPotato"
        if "thedefiant" in u: return "The Defiant"
        return "RSS"

    async def _parse_feed_url(self, url: str):
        # feedparser.parse(url) faz I/O e pode bloquear; então jogamos pra thread
        return await asyncio.to_thread(feedparser.parse, url)

    async def fetch_lines(self, session=None, *, limit: int | None = None, **_) -> tuple[list[NewsLine], list[str]]:
        items: list[NewsLine] = []
        sources: list[str] = []

        if not self.feeds_en:
            return [], []

        for it in self.feeds_en:
            if isinstance(it, (tuple, list)) and len(it) == 2:
                src, url = str(it[0]), str(it[1])
            else:
                url = str(it)
                src = self._guess_source(url)

            try:
                feed = await self._parse_feed_url(url)
                if getattr(feed, "bozo", False):
                    continue

                sources.append(src)
                for entry in (feed.entries or [])[:10]:
                    en = _clean(getattr(entry, "title", ""))
                    if not en:
                        continue
                    pt = _pt_headline(en)
                    items.append(NewsLine(pt=pt, en=en, source=src))
            except Exception:
                continue

        # dedupe por EN
        seen = set()
        out: list[NewsLine] = []
        for x in items:
            k = (x.en or "").strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(x)

        # ✅ AQUI é onde o "limit" entra (com indentação correta)
        if limit is not None:
            out = out[: int(limit)]

        return out, sorted(set(sources))

    # compat com versões que chamam engine_news.fetch(...)
    async def fetch(self, session=None, limit: int | None = None, **kwargs):
        lines, sources = await self.fetch_lines(session, limit=limit, **kwargs)
        pt = [x.pt for x in lines]
        en = [x.en for x in lines]
        translated_ok = True  # offline — sempre “ok” do ponto de vista do engine
        return pt, en, sources, translated_ok
