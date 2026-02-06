from __future__ import annotations
import os
from dataclasses import dataclass


def _bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip() in ("1", "true", "True", "YES", "yes")


@dataclass(frozen=True)
class Settings:
    discord_token: str
    guild_id: str
    sync_commands: bool

    log_level: str
    log_skips: bool

    telegram_token: str
    telegram_chat_id: str

    autotrade_enabled: bool
    binance_api_key: str
    binance_api_secret: str
    binance_testnet: bool


def load_settings() -> Settings:
    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    return Settings(
        discord_token=token,
        guild_id=(os.getenv("GUILD_ID") or "").strip(),
        sync_commands=_bool("SYNC_COMMANDS", "1"),

        log_level=(os.getenv("LOG_LEVEL") or "INFO").strip().upper(),
        log_skips=_bool("LOG_SKIPS", "0"),

        telegram_token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
        telegram_chat_id=(os.getenv("TELEGRAM_CHAT_ID") or "").strip(),

        autotrade_enabled=_bool("AUTOTRADE_ENABLED", "0"),
        binance_api_key=(os.getenv("BINANCE_API_KEY") or "").strip(),
        binance_api_secret=(os.getenv("BINANCE_API_SECRET") or "").strip(),
        binance_testnet=_bool("BINANCE_TESTNET", "0"),
    )
