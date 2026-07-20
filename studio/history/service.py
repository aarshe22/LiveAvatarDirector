from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from studio.db.database import Database, row_dict


class HistoryService:
    def __init__(self, db: Database, data_root: Path, exports_root: Path):
        self.db, self.data_root, self.exports_root = db, data_root, exports_root

    def list(self) -> list[dict]:
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT outputs.*, projects.name AS project_name, projects.renderer
                   FROM outputs JOIN projects ON projects.id=outputs.project_id
                   ORDER BY outputs.created_at DESC"""
            ).fetchall()
        history = []
        known_jobs = set()
        for row in rows:
            output = row_dict(row)
            known_jobs.add(output["job_id"])
            history.append({
                "id": output["id"], "source": "database", "project_id": output["project_id"],
                "project_name": output["project_name"], "job_id": output["job_id"],
                "renderer": output["renderer"], "filename": Path(output["relative_path"]).name,
                "size": output["size"], "duration": output["duration"], "width": output["width"],
                "height": output["height"], "fps": output["fps"], "created_at": output["created_at"],
                "download_url": f"/api/files/download?path={quote(output['relative_path'])}",
            })
        if self.exports_root.exists():
            for path in sorted(self.exports_root.rglob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True):
                relative = path.relative_to(self.exports_root)
                matching_job = next((job_id for job_id in known_jobs if job_id in path.name or job_id[:8] in path.name), None)
                if matching_job:
                    for item in history:
                        if item["job_id"] == matching_job:
                            item["export_download_url"] = f"/api/history/download?path={quote(relative.as_posix())}"
                    continue
                stat = path.stat()
                history.append({
                    "id": f"export:{relative.as_posix()}", "source": "exports", "project_id": None,
                    "project_name": path.stem, "job_id": None, "renderer": None, "filename": path.name,
                    "size": stat.st_size, "duration": None, "width": None, "height": None, "fps": None,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "download_url": f"/api/history/download?path={quote(relative.as_posix())}",
                })
        return sorted(history, key=lambda item: item["created_at"], reverse=True)
