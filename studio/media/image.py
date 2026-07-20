from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageFilter, ImageOps

from studio.storage.atomic import sha256_file


def normalize_portrait(source: Path, target: Path, size: tuple[int, int], mode: str = "smart_blur", fill: str = "#18181b",
                       background_source: Path | None = None) -> dict:
    width, height = size
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original = image.size
        if background_source:
            with Image.open(background_source) as background_opened:
                background_image = ImageOps.exif_transpose(background_opened).convert("RGB")
                canvas = ImageOps.fit(background_image, size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(max(size) / 140))
            foreground = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
            canvas.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
        elif mode == "smart_blur":
            scale = max(width / image.width, height / image.height)
            background = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
            left, top = (background.width - width) // 2, (background.height - height) // 2
            canvas = background.crop((left, top, left + width, top + height)).filter(ImageFilter.GaussianBlur(max(size) / 35))
            foreground = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
            canvas.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
        elif mode == "padding":
            canvas = Image.new("RGB", size, fill)
            foreground = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
            canvas.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
        elif mode == "crop":
            canvas = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.42))
        else: raise ValueError("mode must be smart_blur, padding, or crop")
        canvas.save(temporary, "PNG", optimize=True)
    temporary.replace(target)
    return {"original_dimensions": list(original), "target_dimensions": [width, height], "mode": "style_reference" if background_source else mode,
            "background_source_hash": sha256_file(background_source) if background_source else None,
            "output_hash": sha256_file(target), "distorted": False}
