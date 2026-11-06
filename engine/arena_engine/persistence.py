"""Small transactional SQLite store; all external state changes are atomic."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, state_dir: Path):
        self.path = state_dir / "arena.sqlite3"
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY, phase TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, slot TEXT NOT NULL,
                    status TEXT NOT NULL, data TEXT NOT NULL, internal TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    match_id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL,
                    slot TEXT, reveal_visible INTEGER NOT NULL,
                    PRIMARY KEY(match_id, seq));
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, slot TEXT NOT NULL,
                    path TEXT NOT NULL, reveal_visible INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    actor TEXT NOT NULL, endpoint TEXT NOT NULL, request_id TEXT NOT NULL,
                    digest TEXT NOT NULL, response TEXT NOT NULL, status INTEGER NOT NULL,
                    PRIMARY KEY(actor, endpoint, request_id));
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(artifacts)")}
            if "content_type" not in columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN content_type TEXT NOT NULL DEFAULT 'text/plain'")
            if "filename" not in columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
        os.chmod(self.path, 0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def save_match(db, match):
        db.execute("INSERT INTO matches VALUES(?,?,?) ON CONFLICT(match_id) DO UPDATE "
                   "SET phase=excluded.phase,data=excluded.data",
                   (match["match_id"], match["phase"], json.dumps(match)))

    @staticmethod
    def save_job(db, job, internal, slot):
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE "
                   "SET status=excluded.status,data=excluded.data,internal=excluded.internal",
                   (job["job_id"], job["match_id"], slot, job["status"], json.dumps(job), json.dumps(internal)))
