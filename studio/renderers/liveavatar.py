from __future__ import annotations

import os
import subprocess
from pathlib import Path

from studio.renderers.base import RenderContext, RendererBackend, RendererCapabilities


class LiveAvatarRenderer(RendererBackend):
    def __init__(self, repository: Path, models_root: Path): self.repository, self.models_root = repository, models_root
    @property
    def checkpoint(self) -> Path: return Path(os.getenv("LAD_LIVEAVATAR_CHECKPOINT", self.models_root / "Wan2.2-S2V-14B"))
    def is_available(self) -> bool: return self.checkpoint.is_dir()
    def capabilities(self) -> RendererCapabilities: return RendererCapabilities(name="liveavatar", display_name="LiveAvatar (Wan2.2 S2V 14B)")
    def validate(self, context: RenderContext) -> list[str]: return [] if self.is_available() else [f"checkpoint missing: {self.checkpoint}"]
    def render(self, context: RenderContext, progress) -> None:
        settings = context.settings
        command = ["python3", "minimal_inference/s2v_streaming_interact.py", "--task", "s2v-14B",
                   "--ckpt_dir", str(self.checkpoint), "--image", str(context.portrait), "--audio", str(context.audio),
                   "--prompt", context.prompt or "A natural presenter speaking directly to camera.", "--save_file", str(context.output.with_suffix(".part.mp4")),
                   "--size", settings.get("size", "704*384"), "--num_clip", str(settings["number_of_clips"]),
                   "--infer_frames", str(settings.get("frames_per_clip", 48)), "--sample_steps", str(settings.get("sample_steps", 4)),
                   "--sample_guide_scale", str(settings.get("guidance", 0)), "--base_seed", str(settings.get("seed", 420)), "--single_gpu"]
        if settings.get("fp8"): command.append("--fp8")
        if settings.get("offload_model"): command.extend(["--offload_model", "true"])
        progress(0.05, 0)
        subprocess.run(command, cwd=self.repository, check=True)
        context.output.with_suffix(".part.mp4").replace(context.output); progress(1, settings["number_of_clips"])
