# notifier.py (Atlas Radar v3)
from __future__ import annotations
import os
import aiohttp
import discord
from typing import Optional

class Notifier:
    def __init__(
        self,
        client: discord.Client,
        session: aiohttp.ClientSession,
        telegram_enabled: bool,
        discord_alerts_channel_id: int,
        discord_pulse_channel_id: int,
        role_ping_id: int = 0,
    ):
        self.client = client
        self.session = session
        self.telegram_enabled = telegram_enabled
        self.discord_alerts_channel_id = discord_alerts_channel_id
        self.discord_pulse_channel_id = discord_pulse_channel_id
        self.role_ping_id = role_ping_id

        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.getenv("TELEGRAM_CHAT_ID")

    async def _get_channel(self, channel_id: int) -> Optional[discord.abc.Messageable]:
        if not channel_id:
            return None
        ch = self.client.get_channel(channel_id)
        if ch is None:
            try:
                ch = await self.client.fetch_channel(channel_id)
            except Exception:
                return None
        return ch

    async def send_discord_alert(self, embed: discord.Embed):
        ch = await self._get_channel(self.discord_alerts_channel_id)
        if not ch:
            return
        if self.role_ping_id:
            await ch.send(content=f"<@&{self.role_ping_id}>", embed=embed)
        else:
            await ch.send(embed=embed)

    async def send_discord_pulse(self, embed: discord.Embed):
        ch = await self._get_channel(self.discord_pulse_channel_id)
        if not ch:
            return
        await ch.send(embed=embed)

    async def send_telegram(self, text: str):
        if not self.telegram_enabled:
            return
        if not self.tg_token or not self.tg_chat:
            return
        try:
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            payload = {
                "chat_id": self.tg_chat,
                "text": text,
                "disable_web_page_preview": True,
            }
            async with self.session.post(url, json=payload, timeout=12) as r:
                _ = await r.text()
        except Exception:
            return
