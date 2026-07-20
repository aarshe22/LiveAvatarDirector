from __future__ import annotations

import json
import mimetypes
import shutil
import time
import uuid
from pathlib import Path

from studio.db.database import Database
from studio.storage.atomic import atomic_json, contained, sha256_file


class StorageManager:
    def __init__(self, db: Database, data_root: Path, cache_root: Path, models_root: Path, exports_root: Path):
        self.db, self.data_root, self.cache_root = db, data_root, cache_root
        self.roots = {"data": data_root, "cache": cache_root, "models": models_root, "exports": exports_root}

    def resolve(self, scope: str, relative: str) -> Path:
        if scope not in self.roots: raise ValueError("unknown storage scope")
        return contained(self.roots[scope], self.roots[scope] / relative)

    def references(self) -> tuple[dict[str, list[str]], set[str]]:
        refs: dict[str, list[str]] = {}
        active_projects: set[str] = set()
        with self.db.connect() as db:
            for row in db.execute("SELECT id,active_job_id FROM projects"):
                refs.setdefault(f"projects/{row['id']}/project.json", []).append("project record")
                if row["active_job_id"]: active_projects.add(row["id"])
            for table, column, label in (("assets", "relative_path", "asset"), ("outputs", "relative_path", "render"),
                                         ("outputs", "metadata_path", "render metadata"), ("checkpoints", "relative_path", "checkpoint")):
                for row in db.execute(f"SELECT {column} AS path FROM {table}"):
                    refs.setdefault(row["path"], []).append(label)
            checkpoint_paths = [row["relative_path"] for row in db.execute("SELECT relative_path FROM checkpoints")]
        for relative in checkpoint_paths:
            sidecar = self.data_root / relative
            try:
                for output in json.loads(sidecar.read_text()).get("output_files", []): refs.setdefault(output, []).append("checkpoint output")
            except (OSError, json.JSONDecodeError): continue
        return refs, active_projects

    def list(self, scope: str = "data", project_id: str | None = None, limit: int = 5000) -> list[dict]:
        root = self.roots.get(scope)
        if not root: raise ValueError("unknown storage scope")
        scan = root / "projects" / project_id if scope == "data" and project_id else root
        scan = contained(root, scan); refs, active = self.references(); result = []
        if not scan.exists(): return result
        for path in scan.rglob("*"):
            if not path.is_file() or path.name.endswith(("-wal", "-shm")): continue
            relative = path.relative_to(root).as_posix(); stat = path.stat(); mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            project = relative.split("/")[1] if scope == "data" and relative.startswith("projects/") and len(relative.split("/")) > 2 else None
            reference_list = refs.get(relative, []) if scope == "data" else []
            previewable = mime.startswith(("image/", "audio/", "video/", "text/")) or path.suffix.lower() in {".json", ".log", ".txt"}
            result.append({"scope": scope, "path": relative, "name": path.name, "size": stat.st_size, "modified": stat.st_mtime,
                           "mime_type": mime, "project_id": project, "references": reference_list,
                           "referenced": bool(reference_list), "active": project in active, "previewable": previewable,
                           "mutable": scope == "cache" or (scope == "data" and relative.startswith("projects/"))})
            if len(result) >= limit: break
        return sorted(result, key=lambda item: item["modified"], reverse=True)

    def describe(self, scope: str, relative: str, checksum: bool = False) -> dict:
        target = self.resolve(scope, relative)
        if not target.is_file(): raise FileNotFoundError(relative)
        item = next((value for value in self.list(scope) if value["path"] == relative), None)
        if item is None: raise FileNotFoundError(relative)
        if checksum: item["sha256"] = sha256_file(target)
        return item

    def _assert_mutable(self, scope: str, relative: str) -> Path:
        item = self.describe(scope, relative)
        if not item["mutable"]: raise ValueError("this managed file is read-only")
        if item["active"]: raise ValueError("file belongs to a project with an active job")
        if item["referenced"]: raise ValueError(f"file is referenced as {', '.join(item['references'])}")
        return self.resolve(scope, relative)

    def trash(self, scope: str, relative: str) -> dict:
        source = self._assert_mutable(scope, relative); trash_id = str(uuid.uuid4())
        directory = self.data_root / "trash" / "files" / trash_id; payload = directory / source.name
        directory.mkdir(parents=True, exist_ok=False); shutil.move(str(source), str(payload))
        manifest = {"id": trash_id, "scope": scope, "original_path": relative, "payload": payload.name,
                    "size": payload.stat().st_size, "trashed_at": time.time()}
        atomic_json(directory / "manifest.json", manifest); return manifest

    def trash_list(self) -> list[dict]:
        root = self.data_root / "trash" / "files"; result = []
        if root.exists():
            for manifest in root.glob("*/manifest.json"):
                try: result.append(json.loads(manifest.read_text()))
                except (OSError, json.JSONDecodeError): continue
        return sorted(result, key=lambda item: item["trashed_at"], reverse=True)

    def restore(self, trash_id: str) -> dict:
        directory = contained(self.data_root / "trash" / "files", self.data_root / "trash" / "files" / trash_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file(): raise FileNotFoundError(trash_id)
        manifest = json.loads(manifest_path.read_text()); source = contained(directory, directory / manifest["payload"])
        target = self.resolve(manifest["scope"], manifest["original_path"])
        if target.exists(): raise ValueError("original path is occupied")
        target.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(source), str(target)); manifest_path.unlink(); directory.rmdir()
        return {**manifest, "restored": True}

    def purge(self, trash_id: str) -> dict:
        root = self.data_root / "trash" / "files"; directory = contained(root, root / trash_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file(): raise FileNotFoundError(trash_id)
        manifest = json.loads(manifest_path.read_text()); shutil.rmtree(directory)
        return {**manifest, "purged": True}

    def duplicate(self, scope: str, relative: str) -> dict:
        source = self.resolve(scope, relative)
        if not source.is_file() or scope not in {"data", "cache"}: raise ValueError("file cannot be duplicated")
        index = 1
        while True:
            target = source.with_name(f"{source.stem}-copy-{index}{source.suffix}")
            if not target.exists(): break
            index += 1
        shutil.copy2(source, target); return self.describe(scope, target.relative_to(self.roots[scope]).as_posix())

    def move(self, scope: str, relative: str, destination: str) -> dict:
        source = self._assert_mutable(scope, relative); target = self.resolve(scope, destination)
        if target.exists(): raise ValueError("destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True); source.replace(target)
        return self.describe(scope, target.relative_to(self.roots[scope]).as_posix())
