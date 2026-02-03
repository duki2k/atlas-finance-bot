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

    async def append_trade(self, row: List[Any]) -> bool:
        """Append uma linha na aba trades."""
        def _run():
            body = {"values": [row]}
            self._svc.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.tab_trades}!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()
            return True

        try:
            return await self._to_thread(_run)
        except Exception:
            return False

    async def get_all_trades(self) -> List[List[str]]:
        """Lê todas as linhas da aba trades."""
        def _run():
            resp = self._svc.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.tab_trades}!A:Z"
            ).execute()
            return resp.get("values", [])

        return await self._to_thread(_run)

    async def find_trade_row(self, trade_id: str) -> Tuple[Optional[int], Optional[List[str]], Optional[List[str]]]:
        """
        Retorna: (row_index_1based, header, row)
        row_index_1based: número da linha na planilha (1 = header)
        """
        values = await self.get_all_trades()
        if not values or len(values) < 2:
            return None, None, None

        header = values[0]
        for idx, row in enumerate(values[1:], start=2):
            if len(row) > 0 and row[0] == trade_id:
                return idx, header, row
        return None, header, None

    async def update_trade_by_id(self, trade_id: str, updates: Dict[str, Any]) -> bool:
        """
        Atualiza colunas específicas na linha do trade.
        updates: {col_name: value}
        """
        row_idx, header, row = await self.find_trade_row(trade_id)
        if not row_idx or not header:
            return False

        row = row or []
        row = row + [""] * (len(header) - len(row))

        col_map = {name: i for i, name in enumerate(header)}
        for k, v in updates.items():
            if k in col_map:
                row[col_map[k]] = "" if v is None else str(v)

        def _run():
            body = {"values": [row]}
            self._svc.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.tab_trades}!A{row_idx}:Z{row_idx}",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            return True

        try:
            return await self._to_thread(_run)
        except Exception:
            return False
