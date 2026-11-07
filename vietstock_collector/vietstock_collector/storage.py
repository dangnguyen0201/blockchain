"""SQLite storage: one row per collected snapshot, plus CSV/JSON export."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Optional

from .parser import StockSnapshot

COLUMNS = [f.name for f in fields(StockSnapshot)]
_REAL = {"price", "change", "percent_change", "ipo_price"}
_INT = {"initial_listed_shares", "listed_shares", "outstanding_shares"}


def _sql_type(col: str) -> str:
    return "REAL" if col in _REAL else "INTEGER" if col in _INT else "TEXT"


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {", ".join(f"{c} {_sql_type(c)}" for c in COLUMNS)}
);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time ON snapshots(symbol, collected_at);
"""


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save(self, snap: StockSnapshot) -> None:
        row = snap.to_dict()
        row["sector"] = json.dumps(row["sector"], ensure_ascii=False)
        placeholders = ", ".join("?" for _ in COLUMNS)
        self.conn.execute(
            f"INSERT INTO snapshots ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            [row[c] for c in COLUMNS],
        )
        self.conn.commit()

    def query(self, symbol: Optional[str] = None, latest_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM snapshots"
        params: list = []
        if latest_only:
            sql += " WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY symbol)"
        if symbol:
            sql += (" AND" if latest_only else " WHERE") + " symbol = ?"
            params.append(symbol.upper())
        sql += " ORDER BY symbol, collected_at"
        rows = []
        for r in self.conn.execute(sql, params):
            d = dict(r)
            d.pop("id", None)
            d["sector"] = json.loads(d["sector"]) if d["sector"] else []
            rows.append(d)
        return rows


def export_rows(rows: list[dict], out: str | Path, fmt: str) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "csv":
        with out.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel shows Vietnamese correctly
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({**r, "sector": " > ".join(r.get("sector") or [])})
    else:
        raise ValueError(f"Định dạng không hỗ trợ: {fmt}")
