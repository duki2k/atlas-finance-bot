from __future__ import annotations
import aiohttp
from typing import List, Tuple

# Yahoo Chart endpoint
# Ex: https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1m&range=1d
BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

class YahooData:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def chart(self, ticker: str, interval: str, range_: str = "1d") -> Tuple[List[int], List[float], List[float], List[float], List[float]]:
        url = f"{BASE}/{ticker}"
        params = {"interval": interval, "range": range_}
        async with self.session.get(url, params=params, timeout=15) as r:
            r.raise_for_status()
            j = await r.json()

        result = (j.get("chart") or {}).get("result") or []
        if not result:
            return [], [], [], [], []
        r0 = result[0]
        ts = r0.get("timestamp") or []
        ind = (r0.get("indicators") or {}).get("quote") or []
        if not ind:
            return [], [], [], [], []
        q = ind[0]
        o = q.get("open") or []
        h = q.get("high") or []
        l = q.get("low") or []
        c = q.get("close") or []

        # filtra None
        out_ts, out_o, out_h, out_l, out_c = [], [], [], [], []
        for i in range(min(len(ts), len(c))):
            if c[i] is None or o[i] is None or h[i] is None or l[i] is None:
                continue
            out_ts.append(int(ts[i]))
            out_o.append(float(o[i])); out_h.append(float(h[i])); out_l.append(float(l[i])); out_c.append(float(c[i]))
        return out_ts, out_o, out_h, out_l, out_c
