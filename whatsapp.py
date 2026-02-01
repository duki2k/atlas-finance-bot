import requests
import os

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_TO = os.getenv("WHATSAPP_TO")  # número destino com DDI, ex: 5511999999999

WHATSAPP_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"


def enviar_whatsapp(texto):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID or not WHATSAPP_TO:
        print("⚠️ WhatsApp não configurado corretamente")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_TO,
        "type": "text",
        "text": {
            "body": texto
        }
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    r = requests.post(WHATSAPP_URL, json=payload, headers=headers, timeout=10)

    if r.status_code == 200:
        return True
    else:
        print("Erro WhatsApp:", r.text)
        return False
