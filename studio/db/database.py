from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
 renderer TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 portrait_asset_id TEXT, audio_asset_id TEXT, prompt TEXT NOT NULL DEFAULT '',
 negative_prompt TEXT NOT NULL DEFAULT '', performance_preset TEXT NOT NULL,
 renderer_settings TEXT NOT NULL DEFAULT '{}', active_job_id TEXT, latest_render_id TEXT
);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
 role TEXT NOT NULL, original_name TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
 mime_type TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
 UNIQUE(project_id, kind, sha256)
);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), renderer TEXT NOT NULL,
 state TEXT NOT NULL, phase TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
 current_clip INTEGER NOT NULL DEFAULT 0, total_clips INTEGER NOT NULL DEFAULT 0,
 settings TEXT NOT NULL, idempotency_key TEXT NOT NULL, recovery_level INTEGER NOT NULL DEFAULT 0,
 worker_id TEXT, heartbeat_at TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 started_at TEXT, completed_at TEXT, UNIQUE(project_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT REFERENCES jobs(id), project_id TEXT,
 type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints(
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id), phase TEXT NOT NULL,
 clip_index INTEGER, idempotency_key TEXT NOT NULL, relative_path TEXT NOT NULL,
 sha256 TEXT, valid INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
 UNIQUE(job_id, phase, clip_index, idempotency_key)
);
CREATE TABLE IF NOT EXISTS outputs(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), project_id TEXT NOT NULL,
 relative_path TEXT NOT NULL UNIQUE, metadata_path TEXT NOT NULL, sha256 TEXT NOT NULL,
 size INTEGER NOT NULL, duration REAL, width INTEGER, height INTEGER, fps REAL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created_at);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path): self.path = path

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?, ?)", (SCHEMA_VERSION, utcnow()))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()

    def event(self, type_: str, project_id: str | None = None, job_id: str | None = None, payload: dict | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO events(job_id,project_id,type,payload,created_at) VALUES(?,?,?,?,?)",
                       (job_id, project_id, type_, json.dumps(payload or {}), utcnow()))


def row_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None: return None
    result = dict(row)
    for key in ("metadata", "renderer_settings", "settings", "payload"):
        if key in result and isinstance(result[key], str):
            result[key] = json.loads(result[key])
    return result
