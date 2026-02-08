from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Tuple, Union
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
    Usa padrões comuns + dicionário leve.
    """
    t = _clean(en)

    # padrões comuns de mercado
    patterns = [
        (r"^(?P<who>.+?) shares jump (?P<pct>\d+)% after (?P<why>.+)$",
         lambda m: f"Ações da {m['who']} sobem {m['pct']}% após {m['why']}"),
        (r"^(?P<who>.+?) jumps (?P<pct>\d+)% after (?P<why>.+)$",
         lambda m: f"{m['who']} sobe {m['pct']}% após {m['why']}"),
        (r"^(?P<who>.+?) rockets (?P<pct>\d+)%.*$",
         lambda m: f"{m['who']} dispara {m['pct']}%"),
        (r"^(?P<who>.+?) tumbles below (?P<lvl>[\$€£]?\d[\d,\.]+).*$",
         lambda m: f"{m['who']} cai e fica abaixo de {m['lvl']}"),
        (r"^(?P<who>.+?) falls to (?P<lvl>[\$€£]?\d[\d,\.]+).*$",
         lambda m: f"{m['who']} cai para {m['lvl']}"),
        (r"^Three signs that (?P<who>.+?) price could be near (?P<why>.+)$",
         lambda m: f"Três sinais de que o preço de {m['who']} pode estar perto de {m['why']}"),
        (r"^(?P<who>.+?) is under fire after (?P<why>.+)$",
         lambda m: f"{m['who']} fica sob pressão após {m['why']}"),
        (r"^(?P<who>.+?) prepares to (?P<do>.+)$",
         lambda m: f"{m['who']} se prepara para {m['do']}"),
        (r"^(?P<who>.+?) to exit (?P<where>.+?), reduce staff by (?P<pct>\d+)%.*$",
         lambda m: f"{m['who']} vai sair de {m['where']} e reduzir equipe em {m['pct']}%"),
    ]

    for rx, fn in patterns:
        m = re.match(rx, t, flags=re.IGNORECASE)
        if m:
            out = fn(m.groupdict())
            return out[0].upper() + out[1:] if out else t

    # fallback por dicionário (melhora legibilidade)
    dict_map = {
        "shares": "ações",
        "jump": "sobem",
        "jumps": "sobe",
        "rocket": "dispara",
        "rockets": "dispara",
        "falls": "cai",
        "drops": "cai",
        "plunges": "despenca",
        "crash": "queda",
        "approval": "aprovação",
        "market": "mercado",
        "under fire": "sob pressão",
        "wipes out": "apaga",
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

    # capitaliza
    if out:
        out = out[0].upper() + out[1:]
    return out

class NewsroomEngine:
    def __init__(self, feeds_en=None):
        # ✅ fallback: se não passar feeds_en, puxa do config
        if feeds_en is None:
            feeds_en = getattr(config, "NEWS_RSS_FEEDS_EN", [])
        self.feeds_en = feeds_en or []

    async def fetch_lines(self, session, *, limit: int | None = None, **_):
    # limit = número máximo de notícias (EN/PT)
    # **_ = ignora kwargs antigos/novos sem quebrar
if limit is not None:
    en_lines = en_lines[:limit]
    pt_lines = pt_lines[:limit]


        for it in self.feeds_en:
            # aceita ("Nome", "URL") OU "URL"
            if isinstance(it, (tuple, list)) and len(it) == 2:
                src, url = str(it[0]), str(it[1])
            else:
                url = str(it)
                src = self._guess_source(url)

            try:
                feed = feedparser.parse(url)
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
            k = x.en.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(x)

        return out[:12], sorted(set(sources))

    def _guess_source(self, url: str) -> str:
        u = (url or "").lower()
        if "coindesk" in u: return "CoinDesk"
        if "cointelegraph" in u: return "Cointelegraph"
        if "cryptoslate" in u: return "CryptoSlate"
        if "cryptopotato" in u: return "CryptoPotato"
        if "thedefiant" in u: return "The Defiant"
        return "RSS"
