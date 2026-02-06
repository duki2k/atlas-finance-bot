from __future__ import annotations
import contextlib
import discord
from typing import Optional


class DiscordNotifier:
    def __init__(self, client: discord.Client):
        self.client = client

    async def _get_channel(self, channel_id: int) -> Optional[discord.abc.Messageable]:
        if not channel_id:
            return None
        ch = self.client.get_channel(channel_id)
        if ch is None:
            with contextlib.suppress(Exception):
                ch = await self.client.fetch_channel(channel_id)
        return ch

    async def send_embed(self, channel_id: int, embed: discord.Embed, role_ping_id: int = 0):
        ch = await self._get_channel(channel_id)
        if not ch:
            raise RuntimeError(f"Canal inválido ou sem acesso: {channel_id}")
        if role_ping_id:
            await ch.send(content=f"<@&{role_ping_id}>", embed=embed)
        else:
            await ch.send(embed=embed)
