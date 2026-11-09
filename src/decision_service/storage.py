import json
import sqlite3
from contextlib import closing, contextmanager
from hashlib import sha256


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY NOT NULL,
                    scope TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    project_id TEXT,
                    input_digest TEXT NOT NULL,
                    frozen TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record TEXT NOT NULL,
                    UNIQUE (scope, request_id)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    scope TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    receipt_id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL,
                    PRIMARY KEY (scope, project_id, event_id, revision)
                );
                CREATE TABLE IF NOT EXISTS feedback_decisions (
                    decision_id TEXT NOT NULL REFERENCES decisions(id),
                    receipt_id TEXT NOT NULL REFERENCES feedback(receipt_id),
                    PRIMARY KEY (decision_id, receipt_id)
                );
            """)
        # One service instance owns this file. A request left by a previous
        # instance has no recoverable upstream answer.
        with self.transaction(write=True) as conn:
            for row in conn.execute("SELECT id, record FROM decisions WHERE status = 'processing'").fetchall():
                record = json.loads(row["record"])
                record["status"] = "unknown"
                record["attempts"][-1]["status"] = "unknown"
                record["reason_codes"] = ["interrupted"]
                self.finish(conn, row["id"], record)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def transaction(self, *, write=False):
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn

    @staticmethod
    def finish(conn, decision_id, record):
        conn.execute("UPDATE decisions SET status = ?, record = ? WHERE id = ?",
                     (record["status"], canonical(record), decision_id))

    @staticmethod
    def related_feedback(conn, decision_id):
        rows = conn.execute("""
            SELECT f.receipt_id, f.body, f.revision = (
                SELECT max(g.revision) FROM feedback AS g
                WHERE (g.scope, g.project_id, g.event_id) = (f.scope, f.project_id, f.event_id)
            ) AS is_current
            FROM feedback_decisions AS links
            JOIN feedback AS f ON f.receipt_id = links.receipt_id
            WHERE links.decision_id = ?
            ORDER BY f.event_id, f.revision
        """, (decision_id,))
        return [
            {**json.loads(row["body"]), "receipt_id": row["receipt_id"], "is_current": bool(row["is_current"])}
            for row in rows
        ]
