from __future__ import annotations

import json
import logging
import os
import socket
import time
import traceback
import uuid
from pathlib import Path

from studio.core.config import Settings
from studio.db.database import Database, row_dict, utcnow
from studio.media.audio import clip_plan, normalize_audio, probe
from studio.media.image import normalize_portrait
from studio.projects.service import project_layout
from studio.renderers import registry
from studio.renderers.base import RenderContext
from studio.storage.atomic import atomic_json, sha256_file

LOG = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class Worker:
    def __init__(self, settings: Settings):
        self.settings, self.db = settings, Database(settings.database_path)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        registry.configure(Path(__file__).resolve().parents[2], settings.models_root, settings.mock_renderer)

    def reconcile(self) -> int:
        recovered = []
        with self.db.connect() as db:
            rows = db.execute("SELECT id,project_id,state FROM jobs WHERE state IN ('validating','preprocessing','analyzing','planning','loading_renderer','generating','decoding','encoding','finalizing','validating_output','recovering')").fetchall()
            for row in rows:
                db.execute("UPDATE jobs SET state='queued',phase='recovering',recovery_level=0,worker_id=NULL,updated_at=? WHERE id=?", (utcnow(), row["id"]))
                recovered.append((row["project_id"], row["id"]))
        for project_id, job_id in recovered:
            self.db.event("recovery.completed", project_id, job_id, {"resume_state": "queued", "recovery_level": 0})
        return len(rows)

    def claim(self) -> dict | None:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row: return None
            now = utcnow(); changed = db.execute("UPDATE jobs SET state='validating',phase='validating',worker_id=?,heartbeat_at=?,started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND state='queued'", (self.worker_id, now, now, now, row["id"])).rowcount
            return row_dict(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()) if changed else None

    def transition(self, job: dict, state: str, progress: float | None = None, **fields) -> None:
        with self.db.connect() as db:
            current = db.execute("SELECT state FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if current and current["state"] == "cancel_requested":
            raise JobCancelled("cancel requested")
        values = {"state": state, "phase": state, "updated_at": utcnow(), "heartbeat_at": utcnow(), **fields}
        if progress is not None: values["progress"] = progress
        with self.db.connect() as db:
            db.execute(f"UPDATE jobs SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), job["id"]))
        self.db.event("job.phase_changed", job["project_id"], job["id"], {"phase": state, "progress": progress})

    def checkpoint(self, job: dict, phase: str, path: Path, metadata: dict) -> None:
        base = project_layout(self.settings.data_root, job["project_id"])
        relative = path.relative_to(self.settings.data_root)
        sidecar = base / "work" / "checkpoints" / f"{phase}.json"
        value = {"phase": phase, "project_id": job["project_id"], "job_id": job["id"], "completed_at": utcnow(), "output_files": [str(relative)], "output_hashes": {str(relative): sha256_file(path)}, "valid": True, **metadata}
        atomic_json(sidecar, value)
        with self.db.connect() as db:
            db.execute("INSERT OR REPLACE INTO checkpoints(job_id,phase,clip_index,idempotency_key,relative_path,sha256,valid,created_at) VALUES(?,?,?,?,?,?,1,?)", (job["id"], phase, None, job["idempotency_key"], str(sidecar.relative_to(self.settings.data_root)), sha256_file(sidecar), utcnow()))

    def run(self, job: dict) -> None:
        base = project_layout(self.settings.data_root, job["project_id"])
        with self.db.connect() as db:
            project = row_dict(db.execute("SELECT * FROM projects WHERE id=?", (job["project_id"],)).fetchone())
            portrait = row_dict(db.execute("SELECT * FROM assets WHERE id=?", (project["portrait_asset_id"],)).fetchone())
            audio = row_dict(db.execute("SELECT * FROM assets WHERE id=?", (project["audio_asset_id"],)).fetchone())
            existing_output = row_dict(db.execute("SELECT * FROM outputs WHERE job_id=?", (job["id"],)).fetchone())
        if existing_output:
            existing_path = self.settings.data_root / existing_output["relative_path"]
            if existing_path.is_file() and sha256_file(existing_path) == existing_output["sha256"]:
                self._probe_output(existing_path); now = utcnow()
                with self.db.connect() as db:
                    db.execute("UPDATE jobs SET state='completed',phase='completed',progress=1,error=NULL,completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?", (now, now, job["id"]))
                    db.execute("UPDATE projects SET status='completed',active_job_id=NULL,latest_render_id=?,updated_at=? WHERE id=?", (existing_output["id"], now, project["id"]))
                self.db.event("job.completed", project["id"], job["id"], {"output_id": existing_output["id"], "reused": True})
                return
        backend = registry.get(job["renderer"]); settings = {**project["renderer_settings"], **job["settings"]}
        size_text = settings.get("size", "704x384").replace("*", "x"); width, height = map(int, size_text.split("x"))
        normalized_portrait = base / "assets" / "normalized" / f"portrait-{portrait['sha256'][:12]}-{width}x{height}.png"
        normalized_audio = base / "assets" / "normalized" / f"audio-{audio['sha256'][:12]}.wav"
        self.transition(job, "preprocessing", .05)
        if not normalized_portrait.exists(): normalize_portrait(self.settings.data_root / portrait["relative_path"], normalized_portrait, (width, height), settings.get("normalization_mode", "smart_blur"))
        self.checkpoint(job, "portrait_normalized", normalized_portrait, {})
        if not normalized_audio.exists(): normalize_audio(self.settings.data_root / audio["relative_path"], normalized_audio)
        self.checkpoint(job, "audio_normalized", normalized_audio, {})
        self.transition(job, "analyzing", .15); audio_info = probe(normalized_audio)
        analysis_path = base / "analysis" / f"audio-{audio['sha256'][:12]}.json"; atomic_json(analysis_path, audio_info); self.checkpoint(job, "audio_analysis", analysis_path, {})
        self.transition(job, "planning", .2)
        capabilities = backend.capabilities(); plan = clip_plan(audio_info["duration"], int(settings.get("frames_per_clip", 48)), capabilities.effective_fps)
        settings.update(plan); plan_path = base / "jobs" / job["id"] / "render-plan.json"; atomic_json(plan_path, settings); self.checkpoint(job, "render_plan", plan_path, {})
        with self.db.connect() as db: db.execute("UPDATE jobs SET settings=?,total_clips=? WHERE id=?", (json.dumps(settings), plan["number_of_clips"], job["id"]))
        output = base / "renders" / f"{job['id']}.mp4"
        context = RenderContext(project["id"], job["id"], normalized_portrait, normalized_audio, output, base / "work", project["prompt"], settings)
        errors = backend.validate(context)
        if errors: raise RuntimeError("; ".join(errors))
        self.transition(job, "loading_renderer", .25); backend.prepare(context)
        self.transition(job, "generating", .3)
        last_activity_event = [0.0]
        def progress(value, clip, activity=None):
            now = utcnow(); updates = {"heartbeat_at": now, "updated_at": now}
            if value is not None: updates["progress"] = .3 + .55 * value
            if clip is not None: updates["current_clip"] = clip
            with self.db.connect() as db:
                db.execute(f"UPDATE jobs SET {','.join(k+'=?' for k in updates)} WHERE id=?", (*updates.values(), job["id"]))
            monotonic = time.monotonic()
            if activity and (monotonic - last_activity_event[0] >= 2 or activity.get("stage") != "generating"):
                self.db.event("job.renderer_activity", job["project_id"], job["id"], activity); last_activity_event[0] = monotonic
        backend.render(context, progress)
        self.transition(job, "validating_output", .9)
        info = self._probe_output(output); output_hash = sha256_file(output); output_id = str(uuid.uuid4())
        if abs(info["duration"] - plan["audio_duration"]) > max(0.25, 1 / capabilities.effective_fps):
            raise ValueError(f"output duration {info['duration']:.3f}s differs from source audio {plan['audio_duration']:.3f}s")
        if (info["width"], info["height"]) != (width, height):
            raise ValueError(f"output resolution {info['width']}x{info['height']} does not match plan {width}x{height}")
        metadata = {"schema_version": 1, "output_id": output_id, "job_id": job["id"], "project_id": project["id"], "renderer": job["renderer"], "renderer_capabilities": capabilities.dict(), "input_hashes": {"portrait": portrait["sha256"], "audio": audio["sha256"]}, "settings": settings, "output": info, "sha256": output_hash, "created_at": utcnow()}
        metadata_path = base / "metadata" / f"{job['id']}.json"; atomic_json(metadata_path, metadata); self.checkpoint(job, "output_validated", output, info)
        now = utcnow()
        with self.db.connect() as db:
            db.execute("INSERT INTO outputs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (output_id, job["id"], project["id"], str(output.relative_to(self.settings.data_root)), str(metadata_path.relative_to(self.settings.data_root)), output_hash, output.stat().st_size, info["duration"], info["width"], info["height"], info["fps"], now))
            db.execute("UPDATE jobs SET state='completed',phase='completed',progress=1,completed_at=?,updated_at=? WHERE id=?", (now, now, job["id"]))
            db.execute("UPDATE projects SET status='completed',active_job_id=NULL,latest_render_id=?,updated_at=? WHERE id=?", (output_id, now, project["id"]))
        self.db.event("job.completed", project["id"], job["id"], {"output_id": output_id})

    def _probe_output(self, path: Path) -> dict:
        import subprocess
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout); video = next((x for x in data["streams"] if x["codec_type"] == "video"), None); audio = next((x for x in data["streams"] if x["codec_type"] == "audio"), None)
        if not video or not audio or path.stat().st_size == 0: raise ValueError("final output must contain non-empty video and audio streams")
        numerator, denominator = video.get("avg_frame_rate", "0/1").split("/")
        return {"duration": float(data["format"]["duration"]), "width": video["width"], "height": video["height"], "fps": float(numerator) / float(denominator), "has_audio": True}

    def serve(self, once: bool = False) -> None:
        recovered = self.reconcile(); LOG.info("worker %s ready; reconciled %d jobs", self.worker_id, recovered)
        while True:
            job = self.claim()
            if job:
                try: self.run(job)
                except JobCancelled:
                    now = utcnow()
                    with self.db.connect() as db:
                        db.execute("UPDATE jobs SET state='cancelled',phase='cancelled',updated_at=? WHERE id=?", (now, job["id"]))
                        db.execute("UPDATE projects SET status='draft',active_job_id=NULL,updated_at=? WHERE id=?", (now, job["project_id"]))
                    self.db.event("job.cancelled", job["project_id"], job["id"])
                except Exception as error:
                    LOG.exception("job %s failed", job["id"]); now = utcnow()
                    with self.db.connect() as db:
                        db.execute("UPDATE jobs SET state='failed',phase='failed',error=?,updated_at=? WHERE id=?", (f"{error}\n{traceback.format_exc()}", now, job["id"]))
                        db.execute("UPDATE projects SET status='failed',active_job_id=NULL,updated_at=? WHERE id=?", (now, job["project_id"]))
                    self.db.event("job.failed", job["project_id"], job["id"], {"error": str(error)})
            if once: return
            time.sleep(self.settings.worker_poll_seconds)


def main():
    settings = Settings.load(); logging.basicConfig(level=settings.log_level); Database(settings.database_path).migrate(); Worker(settings).serve()


if __name__ == "__main__": main()
