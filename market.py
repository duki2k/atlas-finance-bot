import yfinance as yf
import pandas as pd

def preco_atual(ativo):
    ticker = yf.Ticker(ativo)
    hist = ticker.history(period="1d")
    return float(hist["Close"].iloc[-1])

def rsi(ativo, periodo=14):
    ticker = yf.Ticker(ativo)
    df = ticker.history(period="1mo")
    delta = df["Close"].diff()
    ganho = delta.where(delta > 0, 0.0)
    perda = -delta.where(delta < 0, 0.0)
    rs = ganho.rolling(periodo).mean() / perda.rolling(periodo).mean()
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def tendencia(ativo):
    ticker = yf.Ticker(ativo)
    df = ticker.history(period="5d")
    if df["Close"].iloc[-1] > df["Close"].iloc[0]:
        return "Alta 📈"
    elif df["Close"].iloc[-1] < df["Close"].iloc[0]:
        return "Baixa 📉"
    return "Lateral ➖"
