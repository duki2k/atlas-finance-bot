import yfinance as yf
import requests

# ─────────────────────────────
# MAPAS
# ─────────────────────────────

CRYPTO_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "USDT-USD": "tether",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "SOL-USD": "solana"
}

# alguns tickers precisam ser tratados explicitamente
STOCK_MAP = {
    "META": "META",
    "GOOGL": "GOOGL",
    "BRK-B": "BRK-B",
}

# ─────────────────────────────
# FUNÇÕES DE CRIPTO
# ─────────────────────────────

def _preco_crypto(ativo):
    coin_id = CRYPTO_MAP.get(ativo)
    if not coin_id:
        raise ValueError("Cripto não mapeada")

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": "usd"
    }

    r = requests.get(url, params=params, timeout=10).json()
    return float(r[coin_id]["usd"])

# ─────────────────────────────
# FUNÇÕES DE AÇÕES
# ─────────────────────────────

def _preco_acao(ativo):
    ticker = STOCK_MAP.get(ativo, ativo)

    df = yf.download(
        ticker,
        period="1d",
        progress=False,
        threads=False
    )

    if df is None or df.empty:
        raise ValueError("Sem dados da ação")

    return float(df["Close"].iloc[-1])

# ─────────────────────────────
# FUNÇÃO PRINCIPAL (USADA PELO BOT)
# ─────────────────────────────

def preco_atual(ativo):
    if ativo.endswith("-USD"):
        return _preco_crypto(ativo)
    return _preco_acao(ativo)

# ─────────────────────────────
# INDICADORES (APENAS AÇÕES)
# ─────────────────────────────

def rsi(ativo, periodo=14):
    if ativo.endswith("-USD"):
        raise ValueError("RSI não disponível para cripto")

    df = yf.download(
        ativo,
        period="1mo",
        progress=False,
        threads=False
    )

    if df is None or df.empty:
        raise ValueError("Sem dados suficientes")

    delta = df["Close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)

    media_ganho = ganho.rolling(periodo).mean()
    media_perda = perda.rolling(periodo).mean()

    rs = media_ganho / media_perda
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


def tendencia(ativo):
    if ativo.endswith("-USD"):
        raise ValueError("Tendência não disponível para cripto")

    df = yf.download(
        ativo,
        period="5d",
        progress=False,
        threads=False
    )

    if df is None or df.empty or len(df) < 2:
        raise ValueError("Sem dados suficientes")

    inicio = df["Close"].iloc[0]
    fim = df["Close"].iloc[-1]

    if fim > inicio:
        return "Alta 📈"
    elif fim < inicio:
        return "Baixa 📉"
    return "Lateral ➖"
