from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from studio.storage.atomic import sha256_file


def probe(path: Path) -> dict:
    run = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    data = json.loads(run.stdout); audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not audio: raise ValueError("uploaded file has no audio stream")
    duration = float(audio.get("duration") or data.get("format", {}).get("duration") or 0)
    return {"duration": duration, "codec": audio.get("codec_name"), "sample_rate": int(audio.get("sample_rate", 0)),
            "channels": audio.get("channels"), "bitrate": int(audio.get("bit_rate") or data.get("format", {}).get("bit_rate") or 0)}


def normalize_audio(source: Path, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True); temporary = target.with_suffix(".part.wav")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)], check=True)
    temporary.replace(target); info = probe(target); info["output_hash"] = sha256_file(target)
    return info


def clip_plan(duration: float, frames_per_clip: int, fps: float) -> dict:
    if duration <= 0 or frames_per_clip <= 0 or fps <= 0: raise ValueError("duration, frames, and fps must be positive")
    clip_duration = frames_per_clip / fps
    return {"audio_duration": duration, "frames_per_clip": frames_per_clip, "effective_fps": fps,
            "clip_duration": clip_duration, "number_of_clips": math.ceil(duration / clip_duration), "trim_to": duration}
