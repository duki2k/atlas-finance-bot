import feedparser

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=bolsas+mundiais+mercado+financeiro+wall+street+economia"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

def noticias():
    try:
        feed = feedparser.parse(RSS_URL)

        if not feed.entries:
            return []

        titulos = []
        for entry in feed.entries[:8]:
            titulos.append(entry.title.strip())

        return titulos

    except Exception as e:
        print("Erro ao buscar notícias:", e)
        return []
