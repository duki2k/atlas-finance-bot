from __future__ import annotations

import aiohttp
from typing import Optional, List


def _split_telegram(text: str, limit: int = 3500) -> List[str]:
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
    Envio via Telegram Bot API.
    Suporta HTML (pra link ficar 'encurtado' como texto clicável).
    """

    def __init__(self, session: aiohttp.ClientSession, token: Optional[str], chat_id: Optional[str]):
        self.session = session
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.last_error: str = ""

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send_text(self, text: str, *, disable_preview: bool = True) -> bool:
        # compat com versões antigas
        return await self.send_message(text, disable_preview=disable_preview, parse_mode=None)

    async def send_html(self, html_text: str, *, disable_preview: bool = True) -> bool:
        return await self.send_message(html_text, disable_preview=disable_preview, parse_mode="HTML")

    async def send_message(self, text: str, *, disable_preview: bool = True, parse_mode: Optional[str] = None) -> bool:
        self.last_error = ""
        if not self.is_configured():
            self.last_error = "TELEGRAM não configurado (token/chat_id vazio)."
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        ok_all = True

        for chunk in _split_telegram(text):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": bool(disable_preview),
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            async with self.session.post(url, json=payload, timeout=20) as r:
                if r.status != 200:
                    ok_all = False
                    try:
                        body = await r.text()
                    except Exception:
                        body = ""
                    self.last_error = f"HTTP {r.status} {body[:200]}".strip()

        return ok_all
