from __future__ import annotations

import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from studio.db.database import Database, row_dict, utcnow
from studio.storage.atomic import atomic_json, persist_stream

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def project_layout(root: Path, project_id: str) -> Path:
    base = root / "projects" / project_id
    for part in ("assets/original", "assets/normalized", "assets/thumbnails", "analysis", "jobs",
                 "work/clips", "work/decoded", "work/checkpoints", "work/temp", "work/cache",
                 "renders", "metadata", "logs", "trash"):
        (base / part).mkdir(parents=True, exist_ok=True)
    return base


class ProjectService:
    def __init__(self, db: Database, data_root: Path): self.db, self.data_root = db, data_root

    def create(self, name: str, mode: str = "singing_avatar", renderer: str = "liveavatar") -> dict:
        project_id, now = str(uuid.uuid4()), utcnow()
        values = (project_id, name.strip() or "Untitled Project", mode, "draft", renderer, now, now, "studio_vocal")
        with self.db.connect() as db:
            db.execute("INSERT INTO projects(id,name,mode,status,renderer,created_at,updated_at,performance_preset) VALUES(?,?,?,?,?,?,?,?)", values)
        project_layout(self.data_root, project_id)
        project = self.get(project_id)
        self._sidecar(project)
        self.db.event("project.created", project_id=project_id)
        return project

    def list(self) -> list[dict]:
        with self.db.connect() as db: rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [row_dict(row) for row in rows]

    def get(self, project_id: str) -> dict:
        with self.db.connect() as db: row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row: raise KeyError(project_id)
        return row_dict(row)

    def update(self, project_id: str, changes: dict) -> dict:
        allowed = {"name", "mode", "renderer", "prompt", "negative_prompt", "performance_preset", "renderer_settings"}
        values = {key: changes[key] for key in changes.keys() & allowed}
        if not values: return self.get(project_id)
        if "renderer_settings" in values: values["renderer_settings"] = json.dumps(values["renderer_settings"])
        values["updated_at"] = utcnow()
        assignments = ",".join(f"{key}=?" for key in values)
        with self.db.connect() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone(): raise KeyError(project_id)
            db.execute(f"UPDATE projects SET {assignments} WHERE id=?", (*values.values(), project_id))
        project = self.get(project_id); self._sidecar(project)
        return project

    def add_asset(self, project_id: str, kind: str, filename: str, stream: BinaryIO, mime_type: str | None = None) -> dict:
        if kind not in {"portrait", "audio", "style"}: raise ValueError("asset kind must be portrait, style, or audio")
        self.get(project_id)
        safe = SAFE_NAME.sub("_", Path(filename).name).strip("._") or f"upload-{uuid.uuid4().hex}"
        asset_id = str(uuid.uuid4())
        relative = Path("projects") / project_id / "assets" / "original" / f"{asset_id}-{safe}"
        digest, size = persist_stream(stream, self.data_root / relative)
        guessed = mime_type or mimetypes.guess_type(safe)[0] or "application/octet-stream"
        allowed = guessed.startswith("image/") if kind in {"portrait", "style"} else guessed.startswith("audio/") or guessed in {"video/mp4", "application/octet-stream"}
        if not allowed:
            (self.data_root / relative).unlink(missing_ok=True); raise ValueError(f"unsupported {kind} MIME type: {guessed}")
        now = utcnow()
        try:
            with self.db.connect() as db:
                db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (asset_id, project_id, kind, "original", filename, str(relative), guessed, size, digest, "{}", now))
                column = {"portrait": "portrait_asset_id", "style": "style_asset_id", "audio": "audio_asset_id"}[kind]
                db.execute(f"UPDATE projects SET {column}=?, updated_at=? WHERE id=?", (asset_id, now, project_id))
        except Exception:
            (self.data_root / relative).unlink(missing_ok=True); raise
        asset = self.asset(asset_id); self._sidecar(self.get(project_id))
        self.db.event("asset.persisted", project_id, payload={"asset_id": asset_id, "kind": kind, "sha256": digest})
        return asset

    def asset(self, asset_id: str) -> dict:
        with self.db.connect() as db: row = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row: raise KeyError(asset_id)
        return row_dict(row)

    def assets(self, project_id: str) -> list[dict]:
        with self.db.connect() as db: rows = db.execute("SELECT * FROM assets WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return [row_dict(r) for r in rows]

    def _sidecar(self, project: dict) -> None:
        project = dict(project); project["schema_version"] = 1
        atomic_json(project_layout(self.data_root, project["id"]) / "project.json", project)
