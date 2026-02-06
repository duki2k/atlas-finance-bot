from __future__ import annotations
import aiohttp


class TelegramNotifier:
    def __init__(self, session: aiohttp.ClientSession, token: str, chat_id: str):
        self.session = session
        self.token = token
        self.chat_id = chat_id

    async def send(self, enabled: bool, text: str):
        if not enabled or not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        async with self.session.post(url, json=payload, timeout=15) as r:
            await r.text()
