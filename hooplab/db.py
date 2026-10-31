"""SQLite persistence (stdlib only)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, level TEXT, coach TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  name TEXT NOT NULL, number INTEGER, position TEXT NOT NULL,
  height_cm INTEGER, hand TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS opponents (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  name TEXT NOT NULL, notes TEXT, scouting TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, title TEXT, date TEXT NOT NULL,
  opponent_id INTEGER REFERENCES opponents(id) ON DELETE SET NULL,
  video_path TEXT, status TEXT NOT NULL DEFAULT 'ready', analysis TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
  opponent_id INTEGER REFERENCES opponents(id) ON DELETE CASCADE,
  type TEXT NOT NULL, outcome INTEGER, zone TEXT, assist INTEGER DEFAULT 0,
  occurred_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
  weight REAL NOT NULL DEFAULT 1.0, meta TEXT,
  play_type TEXT, t_start REAL, t_end REAL);
CREATE INDEX IF NOT EXISTS ix_events_player ON events(player_id);
CREATE INDEX IF NOT EXISTS ix_events_opp ON events(opponent_id);
CREATE TABLE IF NOT EXISTS drill_feedback (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  drill_id TEXT NOT NULL, rating REAL NOT NULL DEFAULT 0, ran INTEGER NOT NULL DEFAULT 0,
  note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, key TEXT NOT NULL,
  value TEXT NOT NULL, PRIMARY KEY (team_id, key));
CREATE TABLE IF NOT EXISTS homework (
  id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  drill_id TEXT NOT NULL, dimension TEXT NOT NULL, target TEXT, due TEXT,
  status TEXT NOT NULL DEFAULT 'assigned', made INTEGER, attempts INTEGER,
  created_at TEXT NOT NULL, playlist_id INTEGER);
CREATE TABLE IF NOT EXISTS custom_drills (
  id TEXT PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  drill TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  messages TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playlists (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  player_id INTEGER REFERENCES players(id) ON DELETE CASCADE, title TEXT NOT NULL, note TEXT,
  items TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feed (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, source TEXT, ref TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, request TEXT NOT NULL, plan TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str = "hooplab.db"):
        self.path = path
        # one connection shared by the API's worker threads: every use goes through this lock
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Additive column migrations for databases created by older versions."""
        wanted = {"events": {"play_type": "TEXT", "t_start": "REAL", "t_end": "REAL"},
                  "homework": {"playlist_id": "INTEGER"}}
        for table, cols in wanted.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.commit()

    @contextmanager
    def tx(self):
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def q(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def insert(self, table: str, row: dict) -> int:
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(row.values()))
            return cur.lastrowid

    def update(self, table: str, row_id: int, fields: dict) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), row_id))

    def delete(self, table: str, row_id: int) -> None:
        with self.tx() as c:
            c.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    # -- domain helpers
    def player_events(self, player_id: int) -> list[dict]:
        return self.q("SELECT * FROM events WHERE player_id = ? ORDER BY occurred_at", (player_id,))

    def opponent_events(self, opponent_id: int) -> list[dict]:
        return self.q("SELECT * FROM events WHERE opponent_id = ?", (opponent_id,))

    def add_events(self, session_id: int, events: list[dict], default_time: str,
                   source: str = "manual") -> int:
        rows = []
        for e in events:
            rows.append((session_id, e.get("player_id"), e.get("opponent_id"), e["type"],
                         None if e.get("outcome") is None else int(bool(e["outcome"])),
                         e.get("zone"), int(bool(e.get("assist"))),
                         e.get("occurred_at") or default_time, e.get("source") or source,
                         float(e.get("weight", 1.0)), json.dumps(e.get("meta")) if e.get("meta") else None,
                         e.get("play_type"), e.get("t_start"), e.get("t_end")))
        with self.tx() as c:
            c.executemany("""INSERT INTO events (session_id, player_id, opponent_id, type, outcome, zone,
                             assist, occurred_at, source, weight, meta, play_type, t_start, t_end)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        return len(rows)

    def settings(self, team_id: int) -> dict:
        return {r["key"]: json.loads(r["value"])
                for r in self.q("SELECT key, value FROM settings WHERE team_id = ?", (team_id,))}

    def set_setting(self, team_id: int, key: str, value) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO settings (team_id, key, value) VALUES (?,?,?) "
                      "ON CONFLICT(team_id, key) DO UPDATE SET value = excluded.value",
                      (team_id, key, json.dumps(value)))
