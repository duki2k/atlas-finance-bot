import yfinance as yf
import pandas as pd

def _get_history(ativo, periodo="1d"):
    ticker = yf.Ticker(ativo)
    hist = ticker.history(period=periodo)

    if hist is None or hist.empty:
        return None

    return hist

def preco_atual(ativo):
    hist = _get_history(ativo, "1d")
    if hist is None:
        raise ValueError("Sem dados para o ativo")
    return float(hist["Close"].iloc[-1])

def rsi(ativo, periodo=14):
    hist = _get_history(ativo, "1mo")
    if hist is None or len(hist) < periodo:
        raise ValueError("Dados insuficientes")

    delta = hist["Close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)

    media_ganho = ganho.rolling(periodo).mean()
    media_perda = perda.rolling(periodo).mean()

    rs = media_ganho / media_perda
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])

def tendencia(ativo):
    hist = _get_history(ativo, "5d")
    if hist is None or len(hist) < 2:
        raise ValueError("Dados insuficientes")

    inicio = hist["Close"].iloc[0]
    fim = hist["Close"].iloc[-1]

    if fim > inicio:
        return "Alta 📈"
    elif fim < inicio:
        return "Baixa 📉"
    return "Lateral ➖"
