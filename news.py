import requests

def noticias():
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "category": "business",
        "language": "pt",
        "pageSize": 5,
        "apiKey": "SUA_API_KEY_NEWSAPI"
    }

    r = requests.get(url, params=params).json()
    if "articles" not in r:
        return ["Não foi possível buscar notícias hoje."]

    return [f"📰 {a['title']}" for a in r["articles"]]
