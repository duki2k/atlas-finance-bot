from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass
class State:
    seen_news: Set[str] = field(default_factory=set)
    last_ts: Dict[str, float] = field(default_factory=dict)

    def mark_news(self, key: str) -> None:
        if key:
            self.seen_news.add(key)

    def cooldown_ok(self, key: str, seconds: int) -> bool:
        """Retorna True se pode enviar e já atualiza o timestamp."""
        now = time.time()
        last = self.last_ts.get(key, 0.0)
        if (now - last) < float(seconds):
            return False
        self.last_ts[key] = now
        return True
