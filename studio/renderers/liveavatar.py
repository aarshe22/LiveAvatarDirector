from __future__ import annotations

import os
import subprocess
from pathlib import Path

from studio.renderers.base import RenderContext, RendererBackend, RendererCapabilities


class LiveAvatarRenderer(RendererBackend):
    def __init__(self, repository: Path, models_root: Path): self.repository, self.models_root = repository, models_root
    @property
    def checkpoint(self) -> Path: return Path(os.getenv("LAD_LIVEAVATAR_CHECKPOINT", self.models_root / "Wan2.2-S2V-14B"))
    @property
    def lora(self) -> Path: return Path(os.getenv("LAD_LIVEAVATAR_LORA", self.models_root / "LiveAvatar"))
    def is_available(self) -> bool: return self.checkpoint.is_dir() and (self.lora / "liveavatar.safetensors").is_file()
    def capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(name="liveavatar", display_name="LiveAvatar (Wan2.2 S2V 14B)", effective_fps=25.0)
    def validate(self, context: RenderContext) -> list[str]:
        errors = []
        if not self.checkpoint.is_dir(): errors.append(f"checkpoint missing: {self.checkpoint}")
        if not (self.lora / "liveavatar.safetensors").is_file(): errors.append(f"LiveAvatar LoRA missing: {self.lora}")
        return errors
    def render(self, context: RenderContext, progress) -> None:
        settings = context.settings
        master_port = 29000 + (int(context.job_id.replace("-", "")[:6], 16) % 1000)
        command = ["torchrun", "--nproc_per_node=1", f"--master_port={master_port}",
                   "minimal_inference/s2v_streaming_interact.py", "--task", "s2v-14B", "--ulysses_size", "1",
                   "--ckpt_dir", str(self.checkpoint), "--image", str(context.portrait), "--audio", str(context.audio),
                   "--prompt", context.prompt or "A natural presenter speaking directly to camera.", "--save_file", str(context.output.with_suffix(".part.mp4")),
                   "--size", settings.get("size", "704*384"), "--num_clip", str(settings["number_of_clips"]),
                   "--infer_frames", str(settings.get("frames_per_clip", 48)), "--sample_steps", str(settings.get("sample_steps", 4)),
                   "--sample_guide_scale", str(settings.get("guidance", 0)), "--base_seed", str(settings.get("seed", 420)),
                   "--training_config", "liveavatar/configs/s2v_causal_sft.yaml", "--load_lora", "--lora_path_dmd", str(self.lora / "liveavatar.safetensors"),
                   "--convert_model_dtype", "--num_gpus_dit", "1", "--single_gpu"]
        if settings.get("fp8", True): command.append("--fp8")
        if settings.get("offload_model"): command.extend(["--offload_model", "true"])
        progress(0.05, 0)
        subprocess.run(command, cwd=self.repository, check=True)
        context.output.with_suffix(".part.mp4").replace(context.output); progress(1, settings["number_of_clips"])
