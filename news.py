import requests

def noticias():
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "category": "business",
        "language": "pt",
        "pageSize": 5,
        "apiKey": "939f315d880e41d7983dedb3ab0c98f1"
    }

    r = requests.get(url, params=params).json()
    if "articles" not in r:
        return ["Não foi possível buscar notícias hoje."]

    return [f"📰 {a['title']}" for a in r["articles"]]
