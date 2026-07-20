from __future__ import annotations

import json
import os
import platform
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studio import __version__
from studio.core.config import Settings
from studio.db.database import Database, row_dict
from studio.jobs.service import JobService
from studio.history.service import HistoryService
from studio.projects.service import ProjectService
from studio.renderers import registry
from studio.storage.atomic import contained
from studio.storage.atomic import atomic_json
from studio.media.audio import clip_plan, probe
from studio.media.image import normalize_portrait

settings = Settings.load(); db = Database(settings.database_path); projects = ProjectService(db, settings.data_root); jobs = JobService(db)
exports_root = Path(os.getenv("LAD_EXPORTS_ROOT", "/exports")).resolve(); history = HistoryService(db, settings.data_root, exports_root)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate(); registry.configure(Path(__file__).resolve().parents[1], settings.models_root, settings.mock_renderer)
    yield


app = FastAPI(title="LiveAvatarDirector", version=__version__, lifespan=lifespan)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mode: str = "singing_avatar"
    renderer: str = "liveavatar"


class ProjectPatch(BaseModel):
    name: str | None = None; mode: str | None = None; renderer: str | None = None; prompt: str | None = None
    negative_prompt: str | None = None; performance_preset: str | None = None; renderer_settings: dict | None = None


def fail(error: Exception):
    if isinstance(error, KeyError): raise HTTPException(404, "resource not found")
    raise HTTPException(400, str(error))


@app.get("/api/health")
def health():
    try:
        with db.connect() as connection: connection.execute("SELECT 1").fetchone()
        database = "ok"
    except Exception as error: database = f"error: {error}"
    return {"status": "ok" if database == "ok" else "degraded", "version": __version__, "database": database, "data_root": str(settings.data_root), "renderers": registry.all()}


@app.get("/api/system")
def system():
    usage = shutil.disk_usage(settings.data_root)
    return {"version": __version__, "python": platform.python_version(), "platform": platform.platform(), "disk": {"total": usage.total, "used": usage.used, "free": usage.free}, "pid": os.getpid()}


@app.get("/api/renderers")
def renderers(): return registry.all()


@app.get("/api/projects")
def list_projects(): return projects.list()


@app.post("/api/projects", status_code=201)
def create_project(value: ProjectCreate):
    try: return projects.create(value.name, value.mode, value.renderer)
    except Exception as error: fail(error)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        project = projects.get(project_id)
        analysis_path = settings.data_root / "projects" / project_id / "analysis" / "latest.json"
        analysis = json.loads(analysis_path.read_text()) if analysis_path.is_file() else None
        if analysis and analysis.get("input_asset_ids") != {"portrait": project["portrait_asset_id"], "audio": project["audio_asset_id"]}:
            analysis = None
        return {**project, "assets": projects.assets(project_id), "analysis": analysis}
    except Exception as error: fail(error)


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, value: ProjectPatch):
    try: return projects.update(project_id, value.model_dump(exclude_none=True))
    except Exception as error: fail(error)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, confirm: bool = False):
    if not confirm: raise HTTPException(409, "deletion requires confirm=true")
    try: project = projects.get(project_id)
    except Exception as error: fail(error)
    if project["active_job_id"]: raise HTTPException(409, "files referenced by an active job cannot be deleted")
    source = settings.data_root / "projects" / project_id
    destination = settings.data_root / "trash" / "projects" / f"{project_id}-{int(time.time())}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.exists(): source.replace(destination)
    try:
        with db.connect() as connection:
            connection.execute("DELETE FROM checkpoints WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)", (project_id,))
            connection.execute("DELETE FROM events WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM outputs WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM assets WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
    except Exception:
        if destination.exists(): destination.replace(source)
        raise
    return {"deleted": project_id, "recoverable_from": str(destination.relative_to(settings.data_root))}


@app.post("/api/projects/{project_id}/portrait", status_code=201)
def upload_portrait(project_id: str, file: UploadFile = File(...)):
    try: return projects.add_asset(project_id, "portrait", file.filename or "portrait", file.file, file.content_type)
    except Exception as error: fail(error)


@app.post("/api/projects/{project_id}/audio", status_code=201)
def upload_audio(project_id: str, file: UploadFile = File(...)):
    try: return projects.add_asset(project_id, "audio", file.filename or "audio", file.file, file.content_type)
    except Exception as error: fail(error)


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str, frames_per_clip: int = 48):
    try:
        project = projects.get(project_id)
        if not project["portrait_asset_id"]: raise ValueError("portrait is required")
        if not project["audio_asset_id"]: raise ValueError("audio is required")
        portrait = projects.asset(project["portrait_asset_id"]); audio = projects.asset(project["audio_asset_id"])
        renderer = registry.get(project["renderer"]); capabilities = renderer.capabilities()
        size_text = project["renderer_settings"].get("size", capabilities.supported_sizes[0]).replace("*", "x")
        width, height = map(int, size_text.split("x")); mode = project["renderer_settings"].get("normalization_mode", "smart_blur")
        preview = settings.data_root / "projects" / project_id / "assets" / "normalized" / f"portrait-{portrait['sha256'][:12]}-{width}x{height}.png"
        portrait_info = normalize_portrait(settings.data_root / portrait["relative_path"], preview, (width, height), mode)
        information = probe(settings.data_root / audio["relative_path"]); plan = clip_plan(information["duration"], frames_per_clip, capabilities.effective_fps)
        result = {**information, "render_plan": plan, "portrait": portrait_info,
                  "input_asset_ids": {"portrait": portrait["id"], "audio": audio["id"]},
                  "preview_url": f"/api/files/download?path={preview.relative_to(settings.data_root)}"}
        analysis_root = settings.data_root / "projects" / project_id / "analysis"
        atomic_json(analysis_root / f"audio-{audio['sha256'][:12]}.json", result); atomic_json(analysis_root / "latest.json", result)
        db.event("audio.analyzed", project_id, payload=result); return result
    except Exception as error: fail(error)


@app.post("/api/projects/{project_id}/render", status_code=202)
def render_project(project_id: str, render_settings: dict | None = None):
    try: return jobs.create(projects.get(project_id), render_settings or {})
    except Exception as error: fail(error)


@app.get("/api/projects/{project_id}/renders")
def project_renders(project_id: str):
    with db.connect() as connection: rows = connection.execute("SELECT * FROM outputs WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/jobs")
def list_jobs(): return jobs.list()


@app.get("/api/history")
def render_history(): return history.list()


@app.get("/api/history/download")
def download_history(path: str):
    try: target = contained(exports_root, exports_root / path)
    except ValueError as error: fail(error)
    if not target.is_file(): raise HTTPException(404, "export not found")
    return FileResponse(target, filename=target.name, media_type="video/mp4")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        result = jobs.get(job_id)
        with db.connect() as connection: events = connection.execute("SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT 200", (job_id,)).fetchall()
        result["events"] = [row_dict(e) for e in events]; return result
    except Exception as error: fail(error)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    try: return jobs.cancel(job_id)
    except Exception as error: fail(error)


@app.post("/api/jobs/{job_id}/retry")
@app.post("/api/jobs/{job_id}/resume")
def retry_job(job_id: str):
    try: return jobs.retry(job_id)
    except Exception as error: fail(error)


@app.get("/api/files")
def files(project_id: str | None = None):
    root = settings.data_root / "projects" / project_id if project_id else settings.data_root
    try: root = contained(settings.data_root, root)
    except ValueError as error: fail(error)
    output = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and not path.name.endswith(("-wal", "-shm")):
                stat = path.stat(); output.append({"path": str(path.relative_to(settings.data_root)), "size": stat.st_size, "modified": stat.st_mtime})
    return output[:5000]


@app.get("/api/files/download")
def download(path: str):
    try: target = contained(settings.data_root, settings.data_root / path)
    except ValueError as error: fail(error)
    if not target.is_file(): raise HTTPException(404, "file not found")
    return FileResponse(target)


@app.get("/api/caches")
def caches():
    result = []
    for directory in [settings.cache_root, settings.data_root / "projects"]:
        size = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file()) if directory.exists() else 0
        result.append({"path": str(directory), "size": size, "exists": directory.exists(), "managed": True})
    return result


@app.get("/api/settings")
def get_settings(): return json.loads((settings.data_root / "config" / "application.json").read_text())


@app.patch("/api/settings")
def patch_settings(changes: dict):
    allowed = {"worker_poll_seconds", "stale_job_seconds", "log_level", "mock_renderer"}
    unknown = set(changes) - allowed
    if unknown: raise HTTPException(400, f"unsupported settings: {', '.join(sorted(unknown))}")
    path = settings.data_root / "config" / "application.json"; value = json.loads(path.read_text()); value.update(changes); atomic_json(path, value)
    return {"settings": value, "restart_required": True}


frontend = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
