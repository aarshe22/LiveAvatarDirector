import io
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from studio.core.config import Settings
from studio.db.database import Database
from studio.jobs.service import JobService
from studio.history.service import HistoryService
from studio.media.audio import clip_plan, probe, trim_audio
from studio.media.image import normalize_portrait
from studio.projects.service import ProjectService
from studio.storage.atomic import atomic_json, contained
from studio.workers.worker import Worker


@pytest.fixture
def services(tmp_path):
    settings = Settings(tmp_path, tmp_path / "models", tmp_path / "cache", tmp_path / "database" / "db.sqlite", mock_renderer=True)
    settings.ensure(); db = Database(settings.database_path); db.migrate()
    return settings, db, ProjectService(db, tmp_path)


def test_database_migration_is_idempotent(services):
    settings, db, _ = services; db.migrate(); db.migrate()
    with db.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
        assert "style_asset_id" in {row[1] for row in connection.execute("PRAGMA table_info(projects)")}


def test_project_and_assets_are_persistent_and_idempotent(services):
    settings, db, service = services; project = service.create("Singer")
    asset = service.add_asset(project["id"], "portrait", "../face.png", io.BytesIO(b"image"), "image/png")
    assert (settings.data_root / asset["relative_path"]).read_bytes() == b"image"
    assert (settings.data_root / "projects" / project["id"] / "project.json").exists()
    reloaded = ProjectService(Database(settings.database_path), settings.data_root).get(project["id"])
    assert reloaded["portrait_asset_id"] == asset["id"]


def test_style_reference_is_persisted_on_project(services):
    settings, _, service = services; project = service.create("Styled")
    style = service.add_asset(project["id"], "style", "set.jpg", io.BytesIO(b"image"), "image/jpeg")
    assert service.get(project["id"])["style_asset_id"] == style["id"]


@pytest.mark.parametrize("source_size", [(300, 900), (900, 300), (500, 500), (1800, 300)])
@pytest.mark.parametrize("mode", ["smart_blur", "padding", "crop"])
def test_image_normalization_has_exact_size_without_stretch(tmp_path, source_size, mode):
    source, target = tmp_path / "source.png", tmp_path / "target.png"
    Image.new("RGB", source_size, "red").save(source); metadata = normalize_portrait(source, target, (704, 384), mode)
    with Image.open(target) as result: assert result.size == (704, 384)
    assert metadata["original_dimensions"] == list(source_size) and metadata["distorted"] is False


def test_style_reference_builds_renderer_background(tmp_path):
    source, style, target = tmp_path / "source.png", tmp_path / "style.png", tmp_path / "target.png"
    Image.new("RGB", (300, 600), "red").save(source); Image.new("RGB", (900, 300), "blue").save(style)
    metadata = normalize_portrait(source, target, (704, 384), background_source=style)
    assert metadata["mode"] == "style_reference" and metadata["background_source_hash"]
    with Image.open(target) as result: assert result.size == (704, 384)


def test_clip_calculation_rounds_up():
    assert clip_plan(6.01, 48, 16)["number_of_clips"] == 3


def test_audio_can_be_trimmed_to_requested_render_duration(tmp_path):
    source, target = tmp_path / "source.wav", tmp_path / "trimmed.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(source)], check=True)
    trim_audio(source, target, 0.5)
    assert probe(target)["duration"] == pytest.approx(0.5, abs=0.02)


def test_atomic_json_leaves_no_partial(tmp_path):
    target = tmp_path / "x.json"; atomic_json(target, {"x": 1})
    assert json.loads(target.read_text()) == {"x": 1} and not list(tmp_path.glob("*.part"))


def test_path_traversal_is_rejected(tmp_path):
    with pytest.raises(ValueError): contained(tmp_path, tmp_path / ".." / "escape")


def test_job_submission_is_idempotent(services):
    settings, db, service = services; project = service.create("Singer", renderer="mock")
    service.add_asset(project["id"], "portrait", "face.png", io.BytesIO(b"image"), "image/png")
    service.add_asset(project["id"], "audio", "voice.wav", io.BytesIO(b"audio"), "audio/wav")
    jobs = JobService(db); first = jobs.create(service.get(project["id"]), {}); second = jobs.create(service.get(project["id"]), {})
    assert first["id"] == second["id"]


def test_retry_restores_project_active_job_state(services):
    _, db, service = services; project = service.create("Retry", renderer="mock")
    service.add_asset(project["id"], "portrait", "face.png", io.BytesIO(b"image"), "image/png")
    service.add_asset(project["id"], "audio", "voice.wav", io.BytesIO(b"audio"), "audio/wav")
    jobs = JobService(db); job = jobs.create(service.get(project["id"]), {})
    with db.connect() as connection:
        connection.execute("UPDATE jobs SET state='failed',phase='failed' WHERE id=?", (job["id"],))
        connection.execute("UPDATE projects SET status='failed',active_job_id=NULL WHERE id=?", (project["id"],))
    assert jobs.retry(job["id"])["state"] == "queued"
    retried_project = service.get(project["id"])
    assert retried_project["status"] == "rendering" and retried_project["active_job_id"] == job["id"]


def test_history_discovers_untracked_exports(services, tmp_path):
    settings, db, _ = services
    exports = tmp_path / "exports"; exports.mkdir(); video = exports / "archived render.mp4"; video.write_bytes(b"video")
    history = HistoryService(db, settings.data_root, exports).list()
    assert history[0]["source"] == "exports"
    assert history[0]["filename"] == "archived render.mp4"
    assert history[0]["download_url"].endswith("archived%20render.mp4")


def test_worker_renders_requested_leading_duration_with_style_reference(services, tmp_path):
    settings, db, service = services; project = service.create("Short styled render", renderer="mock")
    portrait_bytes, style_bytes = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (300, 600), "red").save(portrait_bytes, "PNG"); portrait_bytes.seek(0)
    Image.new("RGB", (900, 300), "blue").save(style_bytes, "PNG"); style_bytes.seek(0)
    audio_path = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(audio_path)], check=True)
    service.add_asset(project["id"], "portrait", "portrait.png", portrait_bytes, "image/png")
    service.add_asset(project["id"], "style", "style.png", style_bytes, "image/png")
    service.add_asset(project["id"], "audio", "audio.wav", io.BytesIO(audio_path.read_bytes()), "audio/wav")
    project = service.update(project["id"], {"renderer_settings": {"duration_seconds": 0.5}})
    job = JobService(db).create(project, {}); Worker(settings).serve(once=True)
    completed = JobService(db).get(job["id"])
    assert completed["state"] == "completed"
    with db.connect() as connection: output = connection.execute("SELECT relative_path,duration FROM outputs WHERE job_id=?", (job["id"],)).fetchone()
    assert output["duration"] == pytest.approx(0.5, abs=0.03)
    assert list((settings.data_root / "projects" / project["id"] / "assets" / "normalized").glob("portrait-*-style-*.png"))
