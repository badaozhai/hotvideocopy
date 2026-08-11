#!/usr/bin/env python
"""Build exact, no-redraw identity boards from the supplied dance character assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "workspace" / "dy_7671559890300685604"
OUTPUT_DIR = PROJECT / "references"
CANVAS_SIZE = (1536, 1024)
BACKGROUND = "#15181d"
PANEL = "#24282e"
BORDER = "#747b82"

SPECS = {
    "wukong": {
        "source": ROOT / "assets" / "characters" / "wukong.png",
        "face": (330, 70, 800, 570),
        "costume": (245, 505, 710, 1300),
    },
    "change": {
        "source": ROOT / "assets" / "characters" / "change.png",
        "face": (185, 0, 785, 690),
        "costume": (185, 430, 785, 1450),
    },
}


def panel(canvas: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    width = box[2] - box[0]
    height = box[3] - box[1]
    surface = Image.new("RGB", (width, height), PANEL)
    canvas.paste(surface, box[:2])
    ImageDraw.Draw(canvas).rectangle(box, outline=BORDER, width=2)
    return surface


def paste_contained(
    canvas: Image.Image,
    image: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    panel(canvas, box)
    width = box[2] - box[0] - 24
    height = box[3] - box[1] - 24
    fitted = ImageOps.contain(image, (width, height), method=Image.Resampling.LANCZOS)
    x = box[0] + (box[2] - box[0] - fitted.width) // 2
    y = box[1] + (box[3] - box[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))


def paste_detail(
    canvas: Image.Image,
    image: Image.Image,
    crop: tuple[int, int, int, int],
    box: tuple[int, int, int, int],
) -> None:
    panel(canvas, box)
    detail = ImageOps.fit(
        image.crop(crop),
        (box[2] - box[0] - 24, box[3] - box[1] - 24),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    canvas.paste(detail, (box[0] + 12, box[1] + 12))


def build(name: str, spec: dict) -> Path:
    source = Path(spec["source"])
    if not source.is_file():
        raise FileNotFoundError(source)
    image = Image.open(source).convert("RGB")
    canvas = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    paste_contained(canvas, image, (20, 20, 680, 1004))
    paste_detail(canvas, image, spec["face"], (700, 20, 1516, 500))
    paste_detail(canvas, image, spec["costume"], (700, 524, 1516, 1004))
    output = OUTPUT_DIR / f"{name}_identity_board.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    return output


if __name__ == "__main__":
    for character, character_spec in SPECS.items():
        print(build(character, character_spec))
