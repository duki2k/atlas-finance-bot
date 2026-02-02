import feedparser

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=mercado+financeiro+bolsa+cripto+economia"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

def noticias():
    try:
        feed = feedparser.parse(RSS_URL)

        if not getattr(feed, "entries", None):
            return []

        titulos = []
        for entry in feed.entries[:10]:
            t = getattr(entry, "title", "")
            if t:
                titulos.append(t.strip())

        return titulos

    except Exception:
        return []
