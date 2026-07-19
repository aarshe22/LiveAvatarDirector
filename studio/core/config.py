from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path
    models_root: Path
    cache_root: Path
    database_path: Path
    worker_poll_seconds: float = 1.0
    stale_job_seconds: int = 30
    log_level: str = "INFO"
    mock_renderer: bool = False

    @classmethod
    def load(cls) -> "Settings":
        data = Path(os.getenv("LAD_DATA_ROOT", "/data")).resolve()
        config_dir = data / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        path = config_dir / "application.json"
        raw: dict = {}
        if path.exists():
            raw = json.loads(path.read_text())
        settings = cls(
            data_root=data,
            models_root=Path(os.getenv("LAD_MODELS_ROOT", raw.get("models_root", "/models"))).resolve(),
            cache_root=Path(os.getenv("LAD_CACHE_ROOT", raw.get("cache_root", "/cache"))).resolve(),
            database_path=data / "database" / "liveavatardirector.db",
            worker_poll_seconds=float(os.getenv("LAD_WORKER_POLL_SECONDS", raw.get("worker_poll_seconds", 1))),
            stale_job_seconds=int(os.getenv("LAD_STALE_JOB_SECONDS", raw.get("stale_job_seconds", 30))),
            log_level=os.getenv("LAD_LOG_LEVEL", raw.get("log_level", "INFO")),
            mock_renderer=os.getenv("LAD_MOCK_RENDERER", str(raw.get("mock_renderer", False))).lower() in {"1", "true", "yes"},
        )
        settings.ensure()
        if not path.exists():
            settings.write_public(path)
        return settings

    def ensure(self) -> None:
        directories = [
            self.data_root / "database", self.data_root / "config", self.data_root / "projects",
            self.data_root / "logs", self.data_root / "backups", self.data_root / "imports",
            self.models_root, self.cache_root, self.cache_root / "huggingface", self.cache_root / "torch",
            self.cache_root / "cuda", self.cache_root / "thumbnails", self.cache_root / "previews",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def write_public(self, path: Path | None = None) -> None:
        from studio.storage.atomic import atomic_json
        target = path or self.data_root / "config" / "application.json"
        value = asdict(self)
        value.pop("database_path")
        value["data_root"] = str(value["data_root"])
        value["models_root"] = str(value["models_root"])
        value["cache_root"] = str(value["cache_root"])
        atomic_json(target, value)
