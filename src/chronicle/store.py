"""Append-only event store. SQLite local/standalone, PostgreSQL collector."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .events import fingerprint, now, validate_event


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, location):
        self.location = str(location)
        self.postgres = self.location.startswith(("postgresql://", "postgres://"))
        if not self.postgres:
            Path(self.location).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.setup()

    @contextmanager
    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self.location, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.location, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sql(self, conn, statement, params=()):
        return conn.execute(statement.replace("?", "%s") if self.postgres else statement, params)

    def setup(self):
        seq = "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with self.connect() as c:
            c.execute(f"""CREATE TABLE IF NOT EXISTS events (
                seq {seq}, event_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL,
                project_id TEXT NOT NULL, computer_id TEXT NOT NULL,
                session_key TEXT NOT NULL, occurred_at TEXT NOT NULL,
                received_at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0)""")
            c.execute("CREATE INDEX IF NOT EXISTS events_project ON events(project_id, seq)")
            c.execute("CREATE INDEX IF NOT EXISTS events_queue ON events(delivered, next_attempt)")
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def append(self, events, delivered=False):
        events = [validate_event(e) for e in events]
        accepted = []
        with self.connect() as c:
            if self.postgres:
                # Serialize commit order so a sequence cursor cannot miss a late commit.
                c.execute("SELECT pg_advisory_xact_lock(94732042)")
            for e in events:
                body = json.dumps(e, ensure_ascii=False, sort_keys=True)
                digest = (
                    fingerprint({k: v for k, v in e.items() if k != "occurred_at"})
                    if e["kind"] in {"PreToolUse", "PostToolUse"}
                    else fingerprint(e)
                )
                key = ":".join(e[k] for k in ("computer_id", "session_id", "agent_id"))
                self.sql(
                    c,
                    """INSERT INTO events
                    (event_id,digest,project_id,computer_id,session_key,occurred_at,
                     received_at,kind,body,delivered) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(event_id) DO NOTHING""",
                    (
                        e["event_id"],
                        digest,
                        e["project_id"],
                        e["computer_id"],
                        key,
                        e["occurred_at"],
                        now(),
                        e["kind"],
                        body,
                        int(delivered),
                    ),
                )
                existing = self.sql(
                    c, "SELECT digest FROM events WHERE event_id=?", (e["event_id"],)
                ).fetchone()
                if existing["digest"] != digest:
                    raise ConflictError("Event ID reused with different content")
                accepted.append(e["event_id"])
        return accepted

    def events(self, project_id=None, limit=None):
        # Full projections deliberately have no silent 100/1000-event truncation.
        with self.connect() as c:
            query, params = "SELECT seq, received_at, body FROM events", []
            if project_id:
                query += " WHERE project_id=?"
                params.append(project_id)
            query += " ORDER BY seq"
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            return [
                dict(json.loads(r["body"]), global_sequence=r["seq"], received_at=r["received_at"])
                for r in self.sql(c, query, params).fetchall()
            ]

    def contains(self, event_id):
        with self.connect() as c:
            return (
                self.sql(c, "SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone()
                is not None
            )

    def pending(self, at, limit=100, projects=None):
        with self.connect() as c:
            params = [at]
            query = (
                "SELECT event_id,body,attempts FROM events WHERE delivered=0 AND next_attempt<=?"
            )
            if projects is not None:
                if not projects:
                    return []
                query += " AND project_id IN (" + ",".join("?" for _ in projects) + ")"
                params.extend(projects)
            query += " ORDER BY seq LIMIT ?"
            params.append(limit)
            return [dict(r) for r in self.sql(c, query, params).fetchall()]

    def ack(self, ids):
        with self.connect() as c:
            for eid in ids:
                self.sql(c, "UPDATE events SET delivered=1 WHERE event_id=?", (eid,))

    def retry(self, ids, next_attempt):
        with self.connect() as c:
            for eid in ids:
                self.sql(
                    c,
                    "UPDATE events SET attempts=attempts+1,next_attempt=? WHERE event_id=?",
                    (next_attempt, eid),
                )

    def get_meta(self, key, default=None):
        with self.connect() as c:
            row = self.sql(c, "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row["value"]) if row else default

    def set_meta(self, key, value):
        with self.connect() as c:
            self.sql(
                c,
                "INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def stats(self):
        with self.connect() as c:
            row = c.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN delivered=0 THEN 1 ELSE 0 END) AS pending FROM events"
            ).fetchone()
            return {k: row[k] or 0 for k in ("total", "pending")}

    def purge(self, before=None, project_id=None, include_pending=False):
        terms, params = [], []
        if before:
            terms.append("received_at<?")
            params.append(before)
        if project_id:
            terms.append("project_id=?")
            params.append(project_id)
        if not include_pending:
            terms.append("delivered=1")
        if not terms:
            raise ValueError("Explicit purge scope required")
        with self.connect() as c:
            self.sql(c, "DELETE FROM events WHERE " + " AND ".join(terms), params)
