"""Conversation memory and run traces in SQLite."""
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT);
CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, question TEXT,
    answer TEXT, steps TEXT, llm_calls INTEGER, latency_ms INTEGER, created_at TEXT);
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        with self._con() as con:
            con.executescript(SCHEMA)

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def new_session(self) -> int:
        with self._con() as con:
            return con.execute("INSERT INTO sessions (created_at) VALUES (?)",
                               (datetime.now(timezone.utc).isoformat(),)).lastrowid

    def exists(self, session_id: int) -> bool:
        with self._con() as con:
            return con.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None

    def add_turn(self, session_id: int, question: str, result) -> None:
        with self._con() as con:
            con.execute("INSERT INTO turns (session_id, question, answer, steps, llm_calls, latency_ms, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (session_id, question, result.answer, json.dumps(result.steps, default=str),
                         result.llm_calls, result.latency_ms, datetime.now(timezone.utc).isoformat()))

    def turns(self, session_id: int) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [dict(r, steps=json.loads(r["steps"])) for r in rows]

    def history(self, session_id: int, last: int = 4) -> list[dict]:
        out = []
        for t in self.turns(session_id)[-last:]:
            out += [{"role": "user", "content": t["question"]}, {"role": "assistant", "content": t["answer"]}]
        return out
