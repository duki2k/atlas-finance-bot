from __future__ import annotations
from .state import State
from .observability import DiscordLogger
from .notifier_discord import DiscordNotifier
from .notifier_telegram import TelegramNotifier
from .engines_newsroom import NewsroomEngine


class NewsJob:
    def __init__(
        self,
        state: State,
        logger: DiscordLogger,
        notifier: DiscordNotifier,
        tg: TelegramNotifier,
        engine: NewsroomEngine,
        channel_id: int,
        telegram_enabled: bool,
        discord_invite: str,
    ):
        self.state = state
        self.logger = logger
        self.notifier = notifier
        self.tg = tg
        self.engine = engine
        self.channel_id = int(channel_id or 0)
        self.telegram_enabled = telegram_enabled
        self.discord_invite = discord_invite

    async def run(self):
        items, sources = self.engine.fetch(self.state.seen_news)
        for it in items:
            self.state.mark_news(it.key)

        emb = self.engine.build_embed(items, sources, self.discord_invite)
        await self.notifier.send_embed(self.channel_id, emb)
        await self.logger.info(f"NEWS sent: items={len(items)} sources={len(sources)}")

        text = self.engine.build_telegram(items, sources, self.discord_invite)
        await self.tg.send(self.telegram_enabled, text)
