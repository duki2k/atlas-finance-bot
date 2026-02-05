from __future__ import annotations
import random
import asyncio
import aiohttp
from typing import Any, List, Tuple

BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
HEADERS = {"User-Agent": "AtlasRadarPro/3.1"}

def _to_f(x):
    try:
        return float(x)
    except Exception:
        return None

class BinanceSpot:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _get_json(self, path: str, params: dict, timeout: int = 12, retries: int = 2) -> Any:
        last = None
        for i in range(retries + 1):
            base = random.choice(BASES)
            url = f"{base}{path}"
            try:
                async with self.session.get(url, params=params, headers=HEADERS, timeout=timeout) as r:
                    r.raise_for_status()
                    return await r.json()
            except Exception as e:
                last = e
                await asyncio.sleep((0.25 * (2 ** i)) + random.uniform(0, 0.2))
        return {"_error": str(last) if last else "unknown"}

    async def klines(self, symbol: str, interval: str, limit: int) -> Tuple[List[int], List[float], List[float], List[float], List[float], List[float]]:
        j = await self._get_json("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not isinstance(j, list):
            return [], [], [], [], [], []

        t, o, h, l, c, v = [], [], [], [], [], []
        for row in j:
            ot = int(row[0])
            oo = _to_f(row[1]); hh = _to_f(row[2]); ll = _to_f(row[3]); cc = _to_f(row[4]); vv = _to_f(row[5])
            if None in (oo, hh, ll, cc, vv):
                continue
            t.append(ot); o.append(oo); h.append(hh); l.append(ll); c.append(cc); v.append(vv)

        return t, o, h, l, c, v
