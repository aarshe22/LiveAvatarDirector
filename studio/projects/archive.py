from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO

from studio.db.database import Database, utcnow


class ProjectArchiveService:
    TABLES = ("projects", "assets", "jobs", "events", "checkpoints", "outputs")

    def __init__(self, db: Database, data_root: Path): self.db, self.data_root = db, data_root

    def _snapshot(self, project_id: str) -> dict:
        with self.db.connect() as db:
            project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project: raise KeyError(project_id)
            if project["active_job_id"]: raise ValueError("active projects cannot be archived")
            data = {"projects": [dict(project)]}
            for table in self.TABLES[1:]:
                if table == "checkpoints":
                    rows = db.execute("SELECT checkpoints.* FROM checkpoints JOIN jobs ON jobs.id=checkpoints.job_id WHERE jobs.project_id=?", (project_id,)).fetchall()
                else: rows = db.execute(f"SELECT * FROM {table} WHERE project_id=?", (project_id,)).fetchall()
                data[table] = [dict(row) for row in rows]
        return {"schema_version": 1, "created_at": utcnow(), "project_id": project_id, "database": data}

    def export(self, project_id: str) -> Path:
        manifest = self._snapshot(project_id); source = self.data_root / "projects" / project_id
        if not source.is_dir(): raise FileNotFoundError(source)
        destination = self.data_root / "backups" / f"project-{project_id}-{int(time.time())}.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent); os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
                for path in source.rglob("*"):
                    if path.is_file(): archive.write(path, Path("project") / path.relative_to(source))
            os.replace(temporary, destination)
        finally: temporary.unlink(missing_ok=True)
        return destination

    def import_stream(self, stream: BinaryIO) -> dict:
        import_id = str(uuid.uuid4()); staging = self.data_root / "imports" / import_id; staging.mkdir(parents=True, exist_ok=False)
        archive_path = staging / "upload.zip"
        try:
            total_upload = 0
            with archive_path.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    total_upload += len(chunk)
                    if total_upload > 20 * 1024**3: raise ValueError("project archive exceeds 20 GiB")
                    output.write(chunk)
            with zipfile.ZipFile(archive_path) as archive:
                total_expanded = 0
                for member in archive.infolist():
                    target = (staging / "extracted" / member.filename).resolve()
                    if not target.is_relative_to((staging / "extracted").resolve()): raise ValueError("archive contains an unsafe path")
                    if member.file_size > 4 * 1024**3: raise ValueError("archive member exceeds 4 GiB")
                    total_expanded += member.file_size
                    if total_expanded > 40 * 1024**3: raise ValueError("expanded project archive exceeds 40 GiB")
                archive.extractall(staging / "extracted")
            manifest_path = staging / "extracted" / "manifest.json"
            if not manifest_path.is_file(): raise ValueError("archive manifest is missing")
            manifest = json.loads(manifest_path.read_text()); project_id = manifest["project_id"]
            source = staging / "extracted" / "project"; destination = self.data_root / "projects" / project_id
            if not source.is_dir(): raise ValueError("archive project files are missing")
            with self.db.connect() as db:
                if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone(): raise ValueError("project already exists")
            if destination.exists(): raise ValueError("project directory already exists")
            source.replace(destination)
            try:
                with self.db.connect() as db:
                    for table in self.TABLES:
                        for row in manifest["database"].get(table, []):
                            values = dict(row)
                            if table in {"events", "checkpoints"}: values.pop("id", None)
                            columns = list(values); placeholders = ",".join("?" for _ in columns)
                            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", tuple(values[key] for key in columns))
                self.db.event("project.imported", project_id=project_id, payload={"archive_schema": manifest.get("schema_version")})
            except Exception:
                if destination.exists(): destination.replace(source)
                raise
            return {"project_id": project_id, "imported": True}
        finally:
            shutil.rmtree(staging, ignore_errors=True)
