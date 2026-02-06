from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Dict, Set


@dataclass
class State:
    seen_news: Set[str] = field(default_factory=set)
    last_sent: Dict[str, float] = field(default_factory=dict)
    debug_enabled: bool = False

    def mark_news(self, key: str):
        self.seen_news.add(key)

    def news_seen(self, key: str) -> bool:
        return key in self.seen_news

    def cooldown_ok(self, key: str, cooldown_sec: int) -> bool:
        now = time.time()
        last = self.last_sent.get(key, 0.0)
        if now - last < cooldown_sec:
            return False
        self.last_sent[key] = now
        return True
