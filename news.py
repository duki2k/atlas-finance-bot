# news.py
import asyncio
import random
import time
import aiohttp
import feedparser

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=mercado+financeiro+bolsa+mundial+economia+wall+street+juros+inflacao"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

_SESSION: aiohttp.ClientSession | None = None

# cache simples (evita bater no RSS toda hora)
_CACHE = {"ts": 0.0, "items": []}
_TTL = 180  # 3 min


def set_session(session: aiohttp.ClientSession):
    global _SESSION
    _SESSION = session


def _get_session() -> aiohttp.ClientSession:
    if _SESSION is None or _SESSION.closed:
        raise RuntimeError("news.py: session não foi configurada. Chame news.set_session() no main.py")
    return _SESSION


async def _fetch_text(url: str, timeout: int = 10, retries: int = 1) -> str:
    session = _get_session()

    for i in range(retries + 1):
        try:
            async with session.get(url, timeout=timeout) as r:
                r.raise_for_status()
                return await r.text()
        except Exception:
            if i >= retries:
                break
            await asyncio.sleep((0.25 * (2 ** i)) + random.uniform(0.0, 0.15))

    return ""


async def noticias(limit: int = 10) -> list[str]:
    """
    Busca RSS de forma async e cacheada.
    """
    now = asyncio.get_event_loop().time()

    # cache válido?
    if (now - _CACHE["ts"]) < _TTL and _CACHE["items"]:
        return _CACHE["items"][:limit]

    xml = await _fetch_text(RSS_URL, timeout=10, retries=1)
    if not xml:
        return []

    try:
        feed = feedparser.parse(xml)
        if not getattr(feed, "entries", None):
            return []

        titulos = []
        for entry in feed.entries[:limit]:
            t = getattr(entry, "title", "")
            if t:
                titulos.append(t.strip())

        # atualiza cache (mesmo que vazio, evita spam de requests em falha)
        _CACHE["ts"] = now
        _CACHE["items"] = titulos

        return titulos

    except Exception:
        return []
