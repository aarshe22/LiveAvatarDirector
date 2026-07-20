from __future__ import annotations

import hashlib
import json
import uuid

from studio.db.database import Database, row_dict, utcnow

ACTIVE = {"queued", "validating", "preprocessing", "analyzing", "planning", "loading_renderer", "generating", "decoding", "encoding", "finalizing", "validating_output", "recovering"}


class JobService:
    def __init__(self, db: Database): self.db = db
    def create(self, project: dict, settings: dict) -> dict:
        if not project["portrait_asset_id"] or not project["audio_asset_id"]: raise ValueError("portrait and audio are required")
        canonical = json.dumps({"portrait": project["portrait_asset_id"], "style": project.get("style_asset_id"), "audio": project["audio_asset_id"], "renderer": project["renderer"], "prompt": project["prompt"], "settings": settings}, sort_keys=True)
        key = hashlib.sha256(canonical.encode()).hexdigest(); now = utcnow(); job_id = str(uuid.uuid4())
        with self.db.connect() as db:
            existing = db.execute("SELECT * FROM jobs WHERE project_id=? AND idempotency_key=?", (project["id"], key)).fetchone()
            if existing and existing["state"] in ACTIVE | {"completed"}: return row_dict(existing)
            db.execute("INSERT INTO jobs(id,project_id,renderer,state,phase,settings,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id, project["id"], project["renderer"], "queued", "queued", json.dumps(settings), key, now, now))
            db.execute("UPDATE projects SET active_job_id=?,status='rendering',updated_at=? WHERE id=?", (job_id, now, project["id"]))
        self.db.event("job.queued", project["id"], job_id)
        return self.get(job_id)
    def get(self, job_id: str) -> dict:
        with self.db.connect() as db: row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row: raise KeyError(job_id)
        return row_dict(row)
    def list(self) -> list[dict]:
        with self.db.connect() as db: rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        result = [row_dict(r) for r in rows]
        with self.db.connect() as db:
            for job in result:
                event = db.execute("SELECT payload,created_at FROM events WHERE job_id=? AND type='job.renderer_activity' ORDER BY id DESC LIMIT 1", (job["id"],)).fetchone()
                if event: job["renderer_activity"] = {**json.loads(event["payload"]), "reported_at": event["created_at"]}
        return result
    def cancel(self, job_id: str) -> dict:
        with self.db.connect() as db: db.execute("UPDATE jobs SET state='cancel_requested',updated_at=? WHERE id=? AND state NOT IN ('completed','failed','cancelled')", (utcnow(), job_id))
        self.db.event("job.cancel_requested", job_id=job_id); return self.get(job_id)
    def retry(self, job_id: str) -> dict:
        with self.db.connect() as db: db.execute("UPDATE jobs SET state='queued',phase='queued',error=NULL,updated_at=? WHERE id=? AND state IN ('failed','cancelled','paused')", (utcnow(), job_id))
        self.db.event("job.retried", job_id=job_id); return self.get(job_id)
