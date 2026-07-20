from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
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
        parameters = (
            {"name": "seed", "label": "Seed", "type": "range", "min": 0, "max": 10000, "step": 1, "default": 420, "help": "Reuses the same starting noise so otherwise identical renders are repeatable."},
            {"name": "sample_steps", "label": "Diffusion steps", "type": "range", "min": 1, "max": 20, "step": 1, "default": 4, "help": "More denoising passes may improve detail but increase render time almost linearly."},
            {"name": "guidance", "label": "Prompt guidance", "type": "range", "min": 0, "max": 10, "step": 0.1, "default": 0, "help": "Controls how strongly motion and appearance follow the text prompt."},
            {"name": "sample_shift", "label": "Sampling shift", "type": "range", "min": 0, "max": 10, "step": 0.1, "default": 3, "help": "Biases the diffusion timestep schedule between global structure and fine detail."},
            {"name": "size", "label": "Output size", "type": "select", "options": ["704x384", "688x368", "720x400", "384x256"], "default": "704x384", "help": "Sets an upstream-supported output resolution and directly affects memory use and render speed."},
            {"name": "fp8", "label": "FP8 inference", "type": "boolean", "default": True, "help": "Uses lower-precision model weights to reduce memory use and improve throughput."},
            {"name": "offload_model", "label": "CPU model offload", "type": "boolean", "default": False, "help": "Moves inactive model components to system RAM, saving VRAM at a speed cost."},
        )
        return RendererCapabilities(name="liveavatar", display_name="LiveAvatar (Wan2.2 S2V 14B)", effective_fps=25.0,
                                    supported_sizes=("704x384", "688x368", "720x400", "384x256"),
                                    supported_frames_per_clip=(48,), generation_parameters=parameters)
    def validate(self, context: RenderContext) -> list[str]:
        errors = []
        if not self.checkpoint.is_dir(): errors.append(f"checkpoint missing: {self.checkpoint}")
        if not (self.lora / "liveavatar.safetensors").is_file(): errors.append(f"LiveAvatar LoRA missing: {self.lora}")
        size = context.settings.get("size", "704x384").replace("*", "x")
        if size not in self.capabilities().supported_sizes: errors.append(f"unsupported LiveAvatar size: {size}")
        return errors
    def render(self, context: RenderContext, progress) -> None:
        settings = context.settings
        master_port = 29000 + (int(context.job_id.replace("-", "")[:6], 16) % 1000)
        command = ["torchrun", "--nproc_per_node=1", f"--master_port={master_port}",
                   "minimal_inference/s2v_streaming_interact.py", "--task", "s2v-14B", "--ulysses_size", "1",
                   "--ckpt_dir", str(self.checkpoint), "--image", str(context.portrait), "--audio", str(context.audio),
                   "--prompt", context.prompt or "A natural presenter speaking directly to camera.", "--save_file", str(context.output.with_suffix(".part.mp4")),
                   "--size", settings.get("size", "704*384").replace("x", "*"), "--num_clip", str(settings["number_of_clips"]),
                   "--infer_frames", str(settings.get("frames_per_clip", 48)), "--sample_steps", str(settings.get("sample_steps", 4)),
                   "--sample_guide_scale", str(settings.get("guidance", 0)), "--base_seed", str(settings.get("seed", 420)),
                   "--sample_shift", str(settings.get("sample_shift", 3)),
                   "--training_config", "liveavatar/configs/s2v_causal_sft.yaml", "--load_lora", "--lora_path_dmd", str(self.lora / "liveavatar.safetensors"),
                   "--convert_model_dtype", "--num_gpus_dit", "1", "--single_gpu"]
        if settings.get("fp8", True): command.append("--fp8")
        command.extend(["--offload_model", "true" if settings.get("offload_model", False) else "false"])
        progress(0.05, 0, {"stage": "launching", "message": "Starting LiveAvatar"})
        process = subprocess.Popen(command, cwd=self.repository, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        blocks = 0
        stage_started: dict[str, float] = {}
        assert process.stdout is not None
        output: queue.Queue[str | None] = queue.Queue()
        def read_output():
            for value in process.stdout: output.put(value)
            output.put(None)
        threading.Thread(target=read_output, daemon=True).start()
        while True:
            try: line = output.get(timeout=5)
            except queue.Empty:
                progress(None, None)
                continue
            if line is None: break
            print(line, end="", flush=True)
            activity = None
            structured = re.search(r"LAD_PROGRESS stage=(\w+) completed=(\d+) total=(\d+)", line)
            if structured:
                stage, completed, total = structured.groups()
                labels = {"diffusion": "Diffusing video clips", "decoding": "Decoding clips through VAE",
                          "encoding": "Encoding video", "muxing": "Muxing source audio"}
                activity = {"stage": stage, "message": labels.get(stage, stage.title()), "units_completed": int(completed),
                            "units_total": int(total), "unit_name": "clips" if stage in {"diffusion", "decoding"} else "step"}
                started = stage_started.setdefault(stage, time.monotonic())
                elapsed = time.monotonic() - started
                if int(completed) > 0 and elapsed > 0:
                    rate = int(completed) / elapsed
                    activity.update({"units_per_second": rate, "seconds_remaining": max(0, (int(total) - int(completed)) / rate)})
                if stage == "diffusion": blocks = int(completed)
            elif "Creating WanS2V pipeline" in line: activity = {"stage": "loading_model", "message": "Loading model"}
            elif "Loading checkpoint shards" in line: activity = {"stage": "loading_checkpoint", "message": "Loading checkpoint shards"}
            elif "LoRA merged successfully" in line: activity = {"stage": "loading_lora", "message": "LoRA loaded"}
            elif "Generating video" in line:
                stage_started["diffusion"] = time.monotonic(); activity = {"stage": "diffusion", "message": "Preparing diffusion"}
            elif "complete full-sequence generation" in line:
                stage_started["decoding"] = time.monotonic(); activity = {"stage": "decoding", "message": "Generation complete; preparing VAE decode"}
            elif "final decode" in line: activity = {"stage": "decoding", "message": "Final VAE decode", "units_completed": blocks, "unit_name": "diffusion blocks"}
            if activity: progress(None, None, activity)
        return_code = process.wait()
        if return_code: raise subprocess.CalledProcessError(return_code, command)
        context.output.with_suffix(".part.mp4").replace(context.output); progress(1, settings["number_of_clips"])
