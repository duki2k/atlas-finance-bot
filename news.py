import feedparser

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q=mercado+financeiro+bolsas+mundiais"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

def noticias():
    feed = feedparser.parse(GOOGLE_NEWS_RSS)

    if not feed.entries:
        return []

    noticias = []
    for entry in feed.entries[:8]:
        titulo = entry.title
        noticias.append(titulo)

    return noticias
