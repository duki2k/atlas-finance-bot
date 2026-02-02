def _store_cache(ativo, preco, variacao):
    if preco is None or variacao is None:
        return
    _last_good[ativo] = (float(preco), float(variacao), time.time())

def _get_cache(ativo, max_age=60 * 60 * 24):
    item = _last_good.get(ativo)
    if not item:
        return None, None
    preco, variacao, ts = item
    if time.time() - ts > max_age:
        return None, None
    return preco, variacao

# ─────────────────────────────
# HELPERS
# ─────────────────────────────

def eh_fii(ativo):
    return ativo.endswith("11.SA")

def _http_get_json(url, params=None, headers=None, timeout=12, retries=2):
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(0.3 * (i + 1))
    return {}

def _last_two_valid(nums):
    vals = []
    for x in reversed(nums or []):
        if x is None:
            continue
        try:
            fx = float(x)
        except:
            continue
        if fx != fx:
            continue
        vals.append(fx)
        if len(vals) == 2:
            return vals[0], vals[1]
    return None, None

def _pct_change(last, prev):
    if last is None or prev is None or prev == 0:
        return None
    return ((last - prev) / prev) * 100.0

# ─────────────────────────────
