# telegram.py
import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensagem: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": mensagem
        }
        r = requests.post(url, json=payload, timeout=12)
        return r.status_code == 200
    except Exception:
        return False
