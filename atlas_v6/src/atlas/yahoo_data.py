from __future__ import annotations

from typing import List, Tuple
import aiohttp


Y_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


class YahooData:
    """Cliente público do Yahoo Finance (sem chave).

    Compatibilidade:
    - chart(ticker, interval, range) -> (ts, o, h, l, c)
    - candles(ticker, interval) -> (o, h, l, c)

    Observação: Yahoo pode retornar None em candles; filtramos.
    """

    def __init__(self, session: aiohttp.ClientSession):
        self.s = session

    async def chart(
        self, ticker: str, interval: str, range_: str = "1d"
    ) -> Tuple[List[int], List[float], List[float], List[float], List[float]]:
        url = f"{Y_BASE}/{ticker}"
        params = {"interval": interval, "range": range_}

        async with self.s.get(url, params=params, timeout=20) as r:
            r.raise_for_status()
            data = await r.json()

        res = (data.get("chart", {}) or {}).get("result") or []
        if not res:
            return [], [], [], [], []

        r0 = res[0] or {}
        ts_raw = r0.get("timestamp") or []
        ts = [int(x) for x in ts_raw if x is not None]

        q = (r0.get("indicators", {}) or {}).get("quote") or []
        if not q:
            return ts, [], [], [], []

        q0 = q[0] or {}

        def _flt(arr):
            return [float(x) for x in (arr or []) if x is not None]

        o = _flt(q0.get("open"))
        h = _flt(q0.get("high"))
        l = _flt(q0.get("low"))
        c = _flt(q0.get("close"))

        # alinhamento básico (Yahoo pode cortar o fim)
        n = min(len(ts) if ts else 10**9, len(o), len(h), len(l), len(c))
        if n <= 0:
            return [], [], [], [], []

        ts = ts[:n] if ts else []
        return ts, o[:n], h[:n], l[:n], c[:n]

    async def candles(self, ticker: str, interval: str) -> Tuple[List[float], List[float], List[float], List[float]]:
        _, o, h, l, c = await self.chart(ticker, interval, "1d")
        return o, h, l, c
