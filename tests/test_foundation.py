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
from studio.media.audio import clip_plan
from studio.media.image import normalize_portrait
from studio.projects.service import ProjectService
from studio.storage.atomic import atomic_json, contained


@pytest.fixture
def services(tmp_path):
    settings = Settings(tmp_path, tmp_path / "models", tmp_path / "cache", tmp_path / "database" / "db.sqlite", mock_renderer=True)
    settings.ensure(); db = Database(settings.database_path); db.migrate()
    return settings, db, ProjectService(db, tmp_path)


def test_database_migration_is_idempotent(services):
    settings, db, _ = services; db.migrate(); db.migrate()
    with db.connect() as connection: assert connection.execute("SELECT version FROM schema_migrations").fetchone()[0] == 1


def test_project_and_assets_are_persistent_and_idempotent(services):
    settings, db, service = services; project = service.create("Singer")
    asset = service.add_asset(project["id"], "portrait", "../face.png", io.BytesIO(b"image"), "image/png")
    assert (settings.data_root / asset["relative_path"]).read_bytes() == b"image"
    assert (settings.data_root / "projects" / project["id"] / "project.json").exists()
    reloaded = ProjectService(Database(settings.database_path), settings.data_root).get(project["id"])
    assert reloaded["portrait_asset_id"] == asset["id"]


@pytest.mark.parametrize("source_size", [(300, 900), (900, 300), (500, 500), (1800, 300)])
@pytest.mark.parametrize("mode", ["smart_blur", "padding", "crop"])
def test_image_normalization_has_exact_size_without_stretch(tmp_path, source_size, mode):
    source, target = tmp_path / "source.png", tmp_path / "target.png"
    Image.new("RGB", source_size, "red").save(source); metadata = normalize_portrait(source, target, (704, 384), mode)
    with Image.open(target) as result: assert result.size == (704, 384)
    assert metadata["original_dimensions"] == list(source_size) and metadata["distorted"] is False


def test_clip_calculation_rounds_up():
    assert clip_plan(6.01, 48, 16)["number_of_clips"] == 3


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


def test_history_discovers_untracked_exports(services, tmp_path):
    settings, db, _ = services
    exports = tmp_path / "exports"; exports.mkdir(); video = exports / "archived render.mp4"; video.write_bytes(b"video")
    history = HistoryService(db, settings.data_root, exports).list()
    assert history[0]["source"] == "exports"
    assert history[0]["filename"] == "archived render.mp4"
    assert history[0]["download_url"].endswith("archived%20render.mp4")
