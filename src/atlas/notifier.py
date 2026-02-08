from __future__ import annotations

import os
import aiohttp
import discord


class Notifier:
    def __init__(self, client: discord.Client, session: aiohttp.ClientSession):
        self.client = client
        self.session = session

        self.tg_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        self.tg_chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    async def send_discord(self, channel_id: int, embed: discord.Embed, role_ping_id: int = 0):
        ch = self.client.get_channel(int(channel_id))
        if ch is None:
            ch = await self.client.fetch_channel(int(channel_id))

        content = ""
        if role_ping_id and int(role_ping_id) > 0:
            content = f"<@&{int(role_ping_id)}>"

        await ch.send(content=content, embed=embed)

    async def send_telegram_text(self, text: str, disable_preview: bool = True):
        if not self.tg_token or not self.tg_chat_id:
            raise RuntimeError("Telegram não configurado (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")

        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": text,
            "disable_web_page_preview": bool(disable_preview),
        }

        async with self.session.post(url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"Telegram HTTP {resp.status}: {body}")

    # compat (caso alguma parte do seu código ainda chame send_text)
    async def send_text(self, text: str, disable_preview: bool = True):
        await self.send_telegram_text(text, disable_preview=disable_preview)
