# storage/sheets.py
import os
import json
import base64
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsStore:
    def __init__(self, spreadsheet_id: str, creds_info: dict, tab_trades: str = "trades"):
        self.spreadsheet_id = spreadsheet_id
        self.tab_trades = tab_trades

        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        self._svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @classmethod
    def from_env(cls) -> Optional["SheetsStore"]:
        sid = os.getenv("GOOGLE_SHEET_ID", "").strip()
        b64 = os.getenv("GOOGLE_SA_B64", "").strip()

        if not sid or not b64:
            return None

        try:
            raw = base64.b64decode(b64.encode("utf-8"))
            info = json.loads(raw.decode("utf-8"))
            return cls(spreadsheet_id=sid, creds_info=info)
        except Exception:
            return None

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(lambda: fn(*args, **kwargs))

    async def ensure_tab(self):
        """Cria a aba trades se não existir (não quebra se já existir)."""
        def _run():
            ss = self._svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheets = ss.get("sheets", [])
            names = {s.get("properties", {}).get("title") for s in sheets}
            if self.tab_trades in names:
                return True

            req = {"requests": [{"addSheet": {"properties": {"title": self.tab_trades}}}]}
            self._svc.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=req
            ).execute()
            return True

        return await self._to_thread(_run)

    as
