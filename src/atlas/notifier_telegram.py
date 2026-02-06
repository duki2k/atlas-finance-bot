from __future__ import annotations

import aiohttp
from typing import Optional, List


def _split_telegram(text: str, limit: int = 3500) -> List[str]:
    """
    Telegram tem limite ~4096 chars por mensagem.
    A gente corta em blocos menores (3500) pra ficar seguro.
    Preferimos quebrar por linhas.
    """
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= limit:
        return [text]

    lines = text.splitlines()
    chunks: List[str] = []
    buff: List[str] = []
    size = 0

    for ln in lines:
        ln2 = ln + "\n"
        if size + len(ln2) > limit and buff:
            chunks.append("".join(buff).strip())
            buff = [ln2]
            size = len(ln2)
        else:
            buff.append(ln2)
            size += len(ln2)

    if buff:
        chunks.append("".join(buff).strip())

    return [c for c in chunks if c]


class TelegramNotifier:
    """
    Envio simples via Bot API:
    - token/chat_id vêm do Railway (env vars)
    - send_text() é o método compatível com o jobs_news.py
    """

    def __init__(self, session: aiohttp.ClientSession, token: Optional[str], chat_id: Optional[str]):
        self.session = session
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()

    async def send_text(self, text: str, *, disable_preview: bool = True) -> bool:
        # Alias pro nome que o seu jobs_news.py está chamando ✅
        return await self.send_message(text, disable_preview=disable_preview)

    async def send_message(self, text: str, *, disable_preview: bool = True) -> bool:
        if not self.token or not self.chat_id:
            # sem config — não explode, só não envia
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        ok_all = True

        for chunk in _split_telegram(text):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": bool(disable_preview),
            }
            async with self.session.post(url, json=payload, timeout=20) as r:
                if r.status != 200:
                    ok_all = False
                    # tenta ler resposta pra debugar
                    try:
                        await r.text()
                    except Exception:
                        pass

        return ok_all
