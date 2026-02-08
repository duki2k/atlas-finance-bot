from __future__ import annotations

from typing import List, Tuple
import aiohttp


class BinanceSpot:
    """
    Cliente público Binance (sem chave).
    Necessário pro Mentor: klines(symbol, interval, limit)
    """

    BASE = "https://api.binance.com"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def klines(
        self, symbol: str, interval: str, limit: int = 50
    ) -> Tuple[List[int], List[float], List[float], List[float], List[float], List[float]]:
        """
        Retorna: t, o, h, l, c, v
        t em ms (open time), o/h/l/c/v floats
        """
        params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
        url = f"{self.BASE}/api/v3/klines"

        async with self.session.get(url, params=params, timeout=20) as r:
            if r.status != 200:
                txt = await r.text()
                raise RuntimeError(f"Binance klines HTTP {r.status}: {txt[:200]}")

            data = await r.json()

        t: List[int] = []
        o: List[float] = []
        h: List[float] = []
        l: List[float] = []
        c: List[float] = []
        v: List[float] = []

        # cada item: [openTime, open, high, low, close, volume, closeTime, ...]
        for row in data:
            t.append(int(row[0]))
            o.append(float(row[1]))
            h.append(float(row[2]))
            l.append(float(row[3]))
            c.append(float(row[4]))
            v.append(float(row[5]))

        return t, o, h, l, c, v
