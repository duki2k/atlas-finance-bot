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
        channel_member_id: int,
        channel_invest_id: int,
        max_member: int,
        max_invest: int,
        telegram_enabled: bool,
        discord_invite: str,
    ):
        self.state = state
        self.logger = logger
        self.notifier = notifier
        self.tg = tg
        self.engine = engine
        self.channel_member_id = int(channel_member_id or 0)
        self.channel_invest_id = int(channel_invest_id or 0)
        self.max_member = int(max_member or 4)
        self.max_invest = int(max_invest or 7)
        self.telegram_enabled = telegram_enabled
        self.discord_invite = discord_invite

    async def run_both(self):
        # Busca uma vez só (pra Membro e Investidor terem o MESMO pacote)
        items, sources = self.engine.fetch(self.state.seen_news, limit=self.max_invest)

        # Monta os dois pacotes
        items_member = items[: self.max_member]
        items_invest = items[: self.max_invest]

        # Envia Discord (membro e invest)
        emb_member = self.engine.build_embed(items_member, sources, self.discord_invite)
        emb_invest = self.engine.build_embed(items_invest, sources, self.discord_invite)

        if self.channel_member_id:
            await self.notifier.send_embed(self.channel_member_id, emb_member)
        if self.channel_invest_id:
            await self.notifier.send_embed(self.channel_invest_id, emb_invest)

        # Marca como "visto" depois de enviar
        for it in items:
            self.state.mark_news(it.key)

        await self.logger.info(f"NEWS sent: member={len(items_member)} invest={len(items_invest)} sources={len(sources)}")

        # Telegram: manda o pacote investidor (mais completo)
        text = self.engine.build_telegram(items_invest, sources, self.discord_invite)
        await self.tg.send(self.telegram_enabled, text)
