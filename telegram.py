# telegram.py
import os
import asyncio
import random
import aiohttp

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

_SESSION: aiohttp.ClientSession | None = None


def set_session(session: aiohttp.ClientSession):
    global _SESSION
    _SESSION = session


def _get_session() -> aiohttp.ClientSession:
    if _SESSION is None or _SESSION.closed:
        raise RuntimeError("telegram.py: session não foi configurada. Chame telegram.set_session() no main.py")
    return _SESSION


async def enviar_telegram(texto: str, timeout: int = 12, retries: int = 1) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    session = _get_session()

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "disable_web_page_preview": True,
    }

    for i in range(retries + 1):
        try:
            async with session.post(url, json=payload, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            if i >= retries:
                break
            await asyncio.sleep((0.3 * (2 ** i)) + random.uniform(0.0, 0.2))

    return False
