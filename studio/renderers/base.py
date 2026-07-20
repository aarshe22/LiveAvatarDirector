from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class RendererCapabilities:
    name: str
    display_name: str
    audio_driven: bool = True
    singing: bool = True
    speech: bool = True
    long_form: bool = True
    native_lip_sync: bool = True
    supported_sizes: tuple[str, ...] = ("704x384", "512x288")
    supported_frames_per_clip: tuple[int, ...] = (48, 80)
    effective_fps: float = 16.0
    fp8: bool = True
    compilation: bool = True
    incremental_decode: bool = False
    generation_resume: bool = False
    recovery_level: int = 0
    generation_parameters: tuple[dict, ...] = field(default_factory=tuple)

    def dict(self): return asdict(self)


@dataclass
class RenderContext:
    project_id: str
    job_id: str
    portrait: Path
    audio: Path
    output: Path
    work_dir: Path
    prompt: str
    settings: dict


class RendererBackend(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def capabilities(self) -> RendererCapabilities: ...
    def validate(self, context: RenderContext) -> list[str]: return []
    def estimate(self, settings: dict) -> dict: return {"estimate_available": False}
    def prepare(self, context: RenderContext) -> None: context.work_dir.mkdir(parents=True, exist_ok=True)
    @abstractmethod
    def render(self, context: RenderContext, progress: Callable[..., None]) -> None: ...
    def cancel(self, context: RenderContext) -> None: return None
    def diagnostics(self) -> dict: return {"available": self.is_available(), "capabilities": self.capabilities().dict()}
