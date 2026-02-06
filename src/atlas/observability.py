from __future__ import annotations
import contextlib
from dataclasses import dataclass
import discord

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}


@dataclass
class DiscordLogger:
    client: discord.Client
    logs_channel_id: int
    level: str = "INFO"

    def _ok(self, lvl: str) -> bool:
        return LEVELS.get(lvl, 20) >= LEVELS.get(self.level, 20)

    async def send(self, lvl: str, msg: str):
        if not self.logs_channel_id or not self._ok(lvl):
            return
        ch = self.client.get_channel(self.logs_channel_id)
        if ch is None:
            with contextlib.suppress(Exception):
                ch = await self.client.fetch_channel(self.logs_channel_id)
        if not ch:
            return

        icon = {"DEBUG": "🧪", "INFO": "📡", "WARN": "⚠️", "ERROR": "🧨"}.get(lvl, "📡")
        with contextlib.suppress(Exception):
            await ch.send(f"{icon} **{lvl}** — {msg}")

    async def debug(self, msg: str): await self.send("DEBUG", msg)
    async def info(self, msg: str): await self.send("INFO", msg)
    async def warn(self, msg: str): await self.send("WARN", msg)
    async def error(self, msg: str): await self.send("ERROR", msg)
