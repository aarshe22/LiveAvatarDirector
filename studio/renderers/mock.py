from __future__ import annotations

import subprocess

from studio.renderers.base import RenderContext, RendererBackend, RendererCapabilities


class MockRenderer(RendererBackend):
    def is_available(self) -> bool: return True
    def capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(name="mock", display_name="Mock Renderer (CI)", fp8=False, compilation=False, recovery_level=1)
    def render(self, context: RenderContext, progress) -> None:
        settings = context.settings; duration = settings["audio_duration"]
        size = settings.get("size", "704x384").replace("*", "x")
        temporary = context.output.with_suffix(".part.mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x171923:s={size}:r=16:d={duration}",
                        "-i", str(context.audio), "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(temporary)], check=True)
        temporary.replace(context.output); progress(1, settings["number_of_clips"])
