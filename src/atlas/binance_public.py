from __future__ import annotations
import aiohttp
from typing import List, Tuple, Dict, Any

BASE = "https://api.binance.com"

class BinancePublic:
    def __init__(self, session: aiohttp.ClientSession):
        self.s = session

    async def klines(self, symbol: str, interval: str = "1h", limit: int = 120) -> List[List[Any]]:
        url = f"{BASE}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
        async with self.s.get(url, params=params, timeout=20) as r:
            r.raise_for_status()
            return await r.json()

    async def ticker24h(self, symbol: str) -> Dict[str, Any]:
        url = f"{BASE}/api/v3/ticker/24hr"
        params = {"symbol": symbol}
        async with self.s.get(url, params=params, timeout=20) as r:
            r.raise_for_status()
            return await r.json()

    async def last_close_and_momentum(self, symbol: str) -> Tuple[float, float]:
        kl = await self.klines(symbol, "1h", 20)
        closes = [float(x[4]) for x in kl if x and x[4] is not None]
        if len(closes) < 5:
            return (closes[-1] if closes else 0.0), 0.0
        # momentum curto: variação das últimas 3 velas
        mom = ((closes[-1] - closes[-4]) / closes[-4]) * 100.0 if closes[-4] > 0 else 0.0
        return closes[-1], mom
