from __future__ import annotations

from pathlib import Path
from studio.renderers.base import RendererBackend
from studio.renderers.liveavatar import LiveAvatarRenderer
from studio.renderers.mock import MockRenderer


class Registry:
    def __init__(self): self.backends: dict[str, RendererBackend] = {}
    def configure(self, repository: Path, models_root: Path, include_mock: bool = False):
        self.backends = {"liveavatar": LiveAvatarRenderer(repository, models_root)}
        if include_mock: self.backends["mock"] = MockRenderer()
    def get(self, name: str) -> RendererBackend:
        if name not in self.backends: raise KeyError(name)
        return self.backends[name]
    def all(self) -> list[dict]: return [backend.diagnostics() for backend in self.backends.values()]


registry = Registry()
