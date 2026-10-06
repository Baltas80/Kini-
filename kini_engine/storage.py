from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .core import Match


class Store:
    def __init__(self, path: str = "data/kini.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS matches(
            date TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
            home_goals INTEGER, away_goals INTEGER, result TEXT,
            PRIMARY KEY(date, home, away)
        )""")
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS predictions(
            created_at TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
            payload TEXT NOT NULL
        )""")
        self.db.commit()

    def insert_matches(self, matches: list[Match]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO matches VALUES(?,?,?,?,?,?)",
            [(str(m.date), m.home, m.away, m.home_goals, m.away_goals, m.result) for m in matches],
        )
        self.db.commit()

    def history(self) -> list[Match]:
        rows = self.db.execute(
            "SELECT date,home,away,home_goals,away_goals,result FROM matches ORDER BY date"
        ).fetchall()
        return [Match(*r) for r in rows]

    def save_prediction(self, home: str, away: str, payload: dict[str, Any], created_at: str) -> None:
        self.db.execute(
            "INSERT INTO predictions VALUES(?,?,?,?)",
            (created_at, home, away, json.dumps(payload, ensure_ascii=False)),
        )
        self.db.commit()
