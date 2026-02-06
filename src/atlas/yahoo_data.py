from __future__ import annotations
import aiohttp
from typing import List, Tuple

Y_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

class YahooData:
    def __init__(self, session: aiohttp.ClientSession):
        self.s = session

    async def candles(self, ticker: str, interval: str) -> Tuple[List[float], List[float], List[float], List[float]]:
        # interval: "5m" | "15m"
        url = f"{Y_BASE}/{ticker}"
        params = {"interval": interval, "range": "1d"}
        async with self.s.get(url, params=params, timeout=20) as r:
            r.raise_for_status()
            data = await r.json()

        res = (data.get("chart", {}) or {}).get("result") or []
        if not res:
            return [], [], [], []

        q = (res[0].get("indicators", {}) or {}).get("quote") or []
        if not q:
            return [], [], [], []

        q0 = q[0]
        o = [x for x in (q0.get("open") or []) if x is not None]
        h = [x for x in (q0.get("high") or []) if x is not None]
        l = [x for x in (q0.get("low") or []) if x is not None]
        c = [x for x in (q0.get("close") or []) if x is not None]
        return o, h, l, c
