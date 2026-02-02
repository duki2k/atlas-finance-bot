diff --git a/telegram.py b/telegram.py
index 48ea3a3e8a4f5fb58d63b7de370c84d08063baca..3897e32d5e2fa832835d78f5c1d870613d078e53 100644
--- a/telegram.py
+++ b/telegram.py
@@ -1,18 +1,20 @@
 import requests
 import os
 
 TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
 TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
 
 def enviar_telegram(texto):
     if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
         return False
 
     url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
     payload = {
         "chat_id": TELEGRAM_CHAT_ID,
-        "text": texto
+        "text": texto,
+        "parse_mode": "Markdown",
+        "disable_web_page_preview": True,
     }
 
     r = requests.post(url, json=payload, timeout=10)
     return r.status_code == 200
