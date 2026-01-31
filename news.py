import feedparser

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q=bolsas+mundiais+mercado+financeiro+wall+street"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

def noticias():
    try:
        feed = feedparser.parse(GOOGLE_NEWS_RSS)

        if not feed.entries:
            return []

        titulos = []
        for entry in feed.entries[:8]:
            if hasattr(entry, "title"):
                titulos.append(entry.title)

        return titulos

    except Exception as e:
        print("Erro no news.py:", e)
        return []
