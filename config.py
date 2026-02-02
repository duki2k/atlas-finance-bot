 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/config.py b/config.py
index 5e388db6ea4c0bdafc48f1d2a8ee292ef7271896..228674c0d07bd16c2d2a824dff088ad70e85b36c 100644
--- a/config.py
+++ b/config.py
@@ -1,31 +1,42 @@
+import os
+
+def _env_int(name, default):
+    value = os.getenv(name)
+    if value is None:
+        return default
+    try:
+        return int(value)
+    except ValueError:
+        return default
+
 ATIVOS = {
     "Criptomoedas": [
         "BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD",
         "ADA-USD","AVAX-USD","DOT-USD","LINK-USD","MATIC-USD"
     ],
 
     "Ações EUA": [
         "AAPL","MSFT","AMZN","GOOGL","NVDA",
         "META","TSLA","BRK-B","JPM","V"
     ],
 
     "Ações Brasil": [
         "PETR4.SA","VALE3.SA","ITUB4.SA","BBDC4.SA","BBAS3.SA",
         "WEGE3.SA","ABEV3.SA","B3SA3.SA","RENT3.SA","SUZB3.SA"
     ],
 
     "FIIs Brasil": [
         "HGLG11.SA","XPML11.SA","MXRF11.SA","VISC11.SA","BCFF11.SA",
         "KNRI11.SA","RECT11.SA","HGRE11.SA","CPTS11.SA","IRDM11.SA"
     ],
 
     "ETFs Globais": [
         "SPY","QQQ","VOO","IVV","VTI",
         "DIA","IWM","EFA","VEA","VNQ"
     ]
 }
 
-CANAL_ANALISE  = 1466255506657251469
-CANAL_NOTICIAS = 1466895475415191583
-CANAL_LOGS     = 1467579765274837064
-CANAL_ADMIN    = 1467296892256911493
+CANAL_ANALISE  = _env_int("DISCORD_CANAL_ANALISE", 1466255506657251469)
+CANAL_NOTICIAS = _env_int("DISCORD_CANAL_NOTICIAS", 1466895475415191583)
+CANAL_LOGS     = _env_int("DISCORD_CANAL_LOGS", 1467579765274837064)
+CANAL_ADMIN    = _env_int("DISCORD_CANAL_ADMIN", 1467296892256911493)
 
EOF
)
