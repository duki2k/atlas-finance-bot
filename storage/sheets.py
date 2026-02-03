import os
import json
import base64
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build


DEFAULT_TAB = "Trades"

HEADER = [
    "trade_id",
    "created_at",
    "created_by",
    "channel_id",
    "message_id",
    "asset",
    "side",
    "timeframe",
    "entry",
    "stop",
    "tp1",
    "tp2",
    "status",
    "closed_at",
    "closed_by",
    "outcome",
    "exit_price",
    "r_multiple",
    "notes",
]


class SheetsStore:
    def __init__(self, spreadsheet_id: str, service_account_b64: str, tab_name: str = DEFAULT_TAB):
        self.spreadsheet_id = spreadsheet_id
        self.service_account_b64 = service_account_b64
        self.tab_name = tab_name
        self._service = None

    @classmethod
    def from_env(cls) -> "SheetsStore":
        sid = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        b64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
        tab = os.getenv("SHEETS_TRADES_TAB", DEFAULT_TAB).strip() or DEFAULT_TAB

        # Se não tiver config, cria "desabilitado" (sem quebrar o bot)
        if not sid or not b64:
            return cls("", "", tab)

        return cls(sid, b64, tab)

    def enabled(self) -> bool:
        return bool(self.spreadsheet_id and self.service_account_b64)

    def _get_service(self):
        if self._service is not None:
            return self._service

        raw = base64.b64decode(self.service_account_b64.encode("utf-8"))
        info = json.loads(raw.decode("utf-8"))

        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )

        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return self._service

    async def ensure_header(self) -> bool:
        if not self.enabled():
            return False

        def _sync():
            svc = self._get_service()
            rng = f"{self.tab_name}!A1:S1"
            resp = svc.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=rng
            ).execute()
            vals = resp.get("values", [])

            if vals and vals[0] and vals[0][: len(HEADER)] == HEADER:
                return True

            body = {"values": [HEADER]}
            svc.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=rng,
                valueInputOption="RAW",
                body=body,
            ).execute()
            return True

        return await asyncio.to_thread(_sync)

    async def append_trade(self, row: Dict[str, Any]) -> bool:
        if not self.enabled():
            return False

        await self.ensure_header()

        values = [[
            row.get("trade_id", ""),
            row.get("created_at", ""),
            row.get("created_by", ""),
            str(row.get("channel_id", "")),
            str(row.get("message_id", "")),
            row.get("asset", ""),
            row.get("side", ""),
            row.get("timeframe", ""),
            row.get("entry", ""),
            row.get("stop", ""),
            row.get("tp1", ""),
            row.get("tp2", ""),
            row.get("status", "OPEN"),
            row.get("closed_at", ""),
            row.get("closed_by", ""),
            row.get("outcome", ""),
            row.get("exit_price", ""),
            row.get("r_multiple", ""),
            row.get("notes", ""),
        ]]

        def _sync():
            svc = self._get_service()
            rng = f"{self.tab_name}!A:S"
            body = {"values": values}
            svc.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=rng,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()
            return True

        return await asyncio.to_thread(_sync)

    async def find_trade_row(self, trade_id: str) -> Optional[int]:
        """
        Retorna o número da linha (1-indexed) onde está o trade_id.
        """
        if not self.enabled():
            return None

        def _sync():
            svc = self._get_service()
            rng = f"{self.tab_name}!A:A"
            resp = svc.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=rng
            ).execute()
            values = resp.get("values", [])
            for idx, row in enumerate(values, start=1):
                if row and row[0].strip() == trade_id.strip():
                    return idx
            return None

        return await asyncio.to_thread(_sync)

    async def close_trade(
        self,
        trade_id: str,
        closed_at: str,
        closed_by: str,
        outcome: str,
        exit_price: str,
        r_multiple: str,
        notes: str = "",
    ) -> bool:
        if not self.enabled():
            return False

        row_idx = await self.find_trade_row(trade_id)
        if not row_idx or row_idx <= 1:
            return False

        # Colunas:
        # M=status, N=closed_at, O=closed_by, P=outcome, Q=exit_price, R=r_multiple, S=notes
        def _sync():
            svc = self._get_service()

            update_range = f"{self.tab_name}!M{row_idx}:S{row_idx}"
            values = [[
                "CLOSED",
                closed_at,
                closed_by,
                outcome,
                exit_price,
                r_multiple,
                notes,
            ]]

            body = {"values": values}
            svc.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=update_range,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            return True

        return await asyncio.to_thread(_sync)

    async def list_trades(self, status: str = "OPEN", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.enabled():
            return []

        def _sync():
            svc = self._get_service()
            rng = f"{self.tab_name}!A:S"
            resp = svc.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=rng
            ).execute()
            values = resp.get("values", [])
            if len(values) < 2:
                return []

            header = values[0]
            rows = values[1:]

            out = []
            for r in rows:
                obj = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
                if status and obj.get("status", "").upper() != status.upper():
                    continue
                out.append(obj)

            out = out[-limit:]  # últimos
            out.reverse()       # mais recente primeiro
            return out

        return await asyncio.to_thread(_sync)
