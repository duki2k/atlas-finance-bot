from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple, Optional

import feedparser

import config


@dataclass
class NewsLine:
    en: str
    pt: str
    source: str


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_site_suffix(title: str) -> str:
    # Remove " - CoinDesk" / " | Cointelegraph" etc
    t = title
    t = re.sub(r"\s+[-|]\s+(CoinDesk|Cointelegraph|CryptoPotato|The Defiant|Decrypt|Bloomberg|Reuters|CNBC|Fortune|WSJ|FT|NYT)\s*$", "", t, flags=re.I)
    return t.strip()


_BASIC_MAP = {
    "surges": "dispara",
    "jumps": "salta",
    "falls": "cai",
    "tumbles": "despenca",
    "rallies": "sobe forte",
    "plunges": "despenca",
    "crashes": "desaba",
    "approves": "aprova",
    "rejects": "rejeita",
    "raises": "capta",
    "sec": "SEC",
    "etf": "ETF",
    "spot": "spot",
    "crypto": "cripto",
    "bitcoin": "Bitcoin",
    "ether": "Ether",
    "ethereum": "Ethereum",
    "xrp": "XRP",
    "stablecoin": "stablecoin",
    "market": "mercado",
    "bill": "projeto de lei",
    "lawsuit": "processo",
    "probe": "investigação",
    "exchange": "exchange",
    "regulator": "regulador",
    "approval": "aprovação",
    "ban": "banimento",
    "launches": "lança",
    "to exit": "vai sair",
    "reduce staff": "reduzir equipe",
    "focus on": "focar em",
    "under fire": "sob críticas",
}


def translate_to_pt(text: str) -> str:
    """
    Tradução *offline* (heurística). Não é perfeita, mas evita depender de API.
    Mantém nomes próprios e termos do mercado.
    """
    t = _clean(text)
    t = _strip_site_suffix(t)

    # substituições por palavras/frases comuns (case-insensitive)
    out = t

    # frases primeiro (mais seguras)
    phrases = [
        ("is under fire", "está sob críticas"),
        ("reduce staff", "reduzir equipe"),
        ("focus on", "focar em"),
        ("market rout", "queda forte do mercado"),
        ("price could be near", "o preço pode estar perto de"),
        ("three signs", "três sinais"),
        ("says one indicator", "diz um indicador"),
        ("violent upside", "alta violenta"),
    ]
    for a, b in phrases:
        out = re.sub(re.escape(a), b, out, flags=re.I)

    # palavras
    def repl_word(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if lw in _BASIC_MAP:
            return _BASIC_MAP[lw]
        return w

    out = re.sub(r"[A-Za-z']+", repl_word, out)

    # ajustes leves de pontuação
    out = re.sub(r"\s+—\s+", " — ", out)
    out = re.sub(r"\s+:\s+", ": ", out)
    return out.strip()


class NewsroomEngine:
    """
    Puxa headlines de RSS (principalmente cripto). Monta pares EN/PT.
    - Sem link no texto final (só fontes no fim).
    - Dedupe simples por título.
    """

    def __init__(self, feeds_en: Optional[Sequence[Tuple[str, str]]] = None, *, cache_max: int = 64):
        self.cache_max = max(10, int(cache_max))
        self.feeds_en: List[Tuple[str, str]] = list(feeds_en or getattr(config, "NEWS_FEEDS_EN", []))
        self._seen: List[str] = []

    def _seen_add(self, key: str):
        key = (key or "").strip().lower()
        if not key:
            return
        if key in self._seen:
            return
        self._seen.append(key)
        if len(self._seen) > self.cache_max:
            self._seen = self._seen[-self.cache_max :]

    def _seen_has(self, key: str) -> bool:
        key = (key or "").strip().lower()
        return bool(key) and (key in self._seen)

    async def fetch_lines(self, session=None, *, limit: Optional[int] = None, **_) -> Tuple[List[NewsLine], List[str]]:
        """
        Retorna (lines, sources). `session` existe só por compat.
        """
        out: List[NewsLine] = []
        sources: List[str] = []

        lim = int(limit) if limit is not None else 8
        lim = max(1, min(lim, 12))

        for source_name, url in self.feeds_en:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    title = _clean(getattr(entry, "title", "") or "")
                    if not title:
                        continue

                    # key p/ dedupe interno
                    key = f"{source_name}::{title}".lower()
                    if self._seen_has(key):
                        continue

                    en = _strip_site_suffix(title)
                    pt = translate_to_pt(en)

                    out.append(NewsLine(en=en, pt=pt, source=source_name))
                    self._seen_add(key)

                    if source_name not in sources:
                        sources.append(source_name)

                    if len(out) >= lim:
                        break
                if len(out) >= lim:
                    break
            except Exception:
                continue

        return out, sources
