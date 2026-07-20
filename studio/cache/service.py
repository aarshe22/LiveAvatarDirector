from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from studio.db.database import Database
from studio.storage.atomic import atomic_json, contained


class CacheService:
    def __init__(self, db: Database, data_root: Path, cache_root: Path): self.db, self.data_root, self.cache_root = db, data_root, cache_root

    @staticmethod
    def _measure(directory: Path) -> tuple[int, int, float | None]:
        size = count = 0; latest = None
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file():
                    stat = path.stat(); size += stat.st_size; count += 1; latest = max(latest or stat.st_mtime, stat.st_mtime)
        return size, count, latest

    def list(self) -> list[dict]:
        with self.db.connect() as db:
            active = {row["id"] for row in db.execute("SELECT id FROM projects WHERE active_job_id IS NOT NULL")}
            any_active = bool(active)
        entries: list[tuple[str, str, Path, str | None, bool]] = []
        known = {"huggingface", "torch", "cuda", "thumbnails", "previews"}
        for name in sorted(known | ({path.name for path in self.cache_root.iterdir()} if self.cache_root.exists() else set())):
            entries.append((f"global:{name}", name, self.cache_root / name, None, any_active))
        projects_root = self.data_root / "projects"
        if projects_root.exists():
            for project in projects_root.iterdir():
                if not project.is_dir(): continue
                for relative in ("work/cache", "work/decoded", "work/temp"):
                    entries.append((f"project:{project.name}:{relative}", relative.split("/")[-1], project / relative, project.name, project.name in active))
        result = []
        for key, name, path, project_id, referenced in entries:
            size, count, latest = self._measure(path)
            result.append({"key": key, "name": name, "path": str(path), "project_id": project_id, "size": size,
                           "file_count": count, "last_used": latest, "exists": path.exists(), "referenced": referenced,
                           "cleanable": not referenced and count > 0})
        return sorted(result, key=lambda item: item["size"], reverse=True)

    def _entry(self, key: str) -> dict:
        entry = next((item for item in self.list() if item["key"] == key), None)
        if not entry: raise KeyError(key)
        return entry

    def clean(self, key: str) -> dict:
        return self._clean_entry(self._entry(key))

    def _clean_entry(self, entry: dict) -> dict:
        if entry["referenced"]: raise ValueError("cache may be referenced by an active job")
        source = Path(entry["path"])
        if not source.exists() or not any(source.iterdir()): return {**entry, "cleaned": False}
        trash_id = str(uuid.uuid4()); destination = self.data_root / "trash" / "caches" / trash_id / "payload"
        destination.parent.mkdir(parents=True, exist_ok=False); shutil.move(str(source), str(destination)); source.mkdir(parents=True, exist_ok=True)
        manifest = {"id": trash_id, "key": entry["key"], "original_path": str(source), "payload": str(destination),
                    "size": entry["size"], "file_count": entry["file_count"], "trashed_at": time.time()}
        atomic_json(destination.parent / "manifest.json", manifest); return {**entry, "cleaned": True, "trash_id": trash_id}

    def clean_safe(self) -> dict:
        cleaned = [self._clean_entry(item) for item in self.list() if item["cleanable"]]
        return {"cleaned": len(cleaned), "bytes_reclaimed": sum(item["size"] for item in cleaned), "entries": cleaned}

    def trash_list(self) -> list[dict]:
        root = self.data_root / "trash" / "caches"; result = []
        if root.exists():
            for path in root.glob("*/manifest.json"):
                try: result.append(json.loads(path.read_text()))
                except (OSError, json.JSONDecodeError): continue
        return sorted(result, key=lambda item: item["trashed_at"], reverse=True)

    def restore(self, trash_id: str) -> dict:
        root = self.data_root / "trash" / "caches"; directory = contained(root, root / trash_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file(): raise FileNotFoundError(trash_id)
        manifest = json.loads(manifest_path.read_text()); payload = contained(directory, Path(manifest["payload"])); target = Path(manifest["original_path"])
        allowed = target.resolve().is_relative_to(self.cache_root.resolve()) or target.resolve().is_relative_to((self.data_root / "projects").resolve())
        if not allowed: raise ValueError("cache restore target is outside managed roots")
        if target.exists() and any(target.iterdir()): raise ValueError("cache target is no longer empty")
        if target.exists(): target.rmdir()
        shutil.move(str(payload), str(target)); manifest_path.unlink(); directory.rmdir(); return {**manifest, "restored": True}

    def purge(self, trash_id: str) -> dict:
        root = self.data_root / "trash" / "caches"; directory = contained(root, root / trash_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file(): raise FileNotFoundError(trash_id)
        manifest = json.loads(manifest_path.read_text()); shutil.rmtree(directory)
        return {**manifest, "purged": True}
