# config.py

CANAL_ADMIN = 1467296892256911493
CANAL_ANALISE = 1466255506657251469
CANAL_NOTICIAS = 1466895475415191583
CANAL_LOGS = 1467579765274837064

NEWS_ATIVAS = True

# Rompimento (%). Sugestão: 1.0 cripto / 1.5 ações / 2.0 fiis.
# Aqui é geral (simples). Depois dá pra separar por categoria.
LIMITE_ROMPIMENTO_PCT = 2.0

# Portfólio por categoria (edite à vontade)
ATIVOS = {
    "🪙 Criptomoedas": [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
        "ADA-USD", "AVAX-USD", "DOT-USD", "LINK-USD", "MATIC-USD",
    ],
    "🇺🇸 Ações EUA": [
        "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA",
        "META", "TSLA", "BRK-B", "JPM", "V",
    ],
    "🇧🇷 Ações Brasil": [
        "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "BBAS3.SA",
        "WEGE3.SA", "ABEV3.SA", "B3SA3.SA", "RENT3.SA", "SUZB3.SA",
    ],
    "🏢 FIIs Brasil": [
        "HGLG11.SA", "XPML11.SA", "MXRF11.SA", "VISC11.SA", "BCFF11.SA",
        "KNRI11.SA", "RECT11.SA", "HGRE11.SA", "CPTS11.SA", "IRDM11.SA",
    ],
    "📦 ETFs EUA": [
        "SPY", "QQQ", "VOO", "IVV", "VTI",
        "DIA", "IWM", "EFA", "VEA", "VNQ",
    ],
}
