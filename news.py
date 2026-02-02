import feedparser

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=mercado+financeiro+bolsa+cripto+economia"
    "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

def noticias():
    try:
        feed = feedparser.parse(RSS_URL)
        return [e.title for e in feed.entries[:8]]
    except:
        return []
