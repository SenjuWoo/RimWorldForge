"""Deterministic, offline procedural art for RimWorld-style assets.

Everything here is drawn locally with Pillow from a seeded palette. No network,
no image model and no paid service is involved. The result is a *starting
asset*: Forge can prove the file exists at the right size and path, but only a
human or vision pass can prove it looks right in game.
"""

from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path
from typing import Any

from .util import read_json, sha256_file, write_json

from PIL import Image, ImageDraw, ImageFont, ImageOps

GEN_VERSION = "rwforge-artgen-1"
SUPERSAMPLE = 4

# Earthy, readable palettes that survive RimWorld's small on-screen sizes.
PALETTES = [
    {"name": "rust", "bg": "#17110d", "base": "#8a4a2c", "dark": "#432116", "light": "#d08a55", "accent": "#e6b45a", "skin": "#c98d64", "metal": "#9aa3ad"},
    {"name": "jade", "bg": "#0d1512", "base": "#2f6b52", "dark": "#173329", "light": "#79b98e", "accent": "#d8c26a", "skin": "#c08a63", "metal": "#a7b3b0"},
    {"name": "indigo", "bg": "#0d1018", "base": "#3b4a7a", "dark": "#1d2440", "light": "#8091c9", "accent": "#d7b56d", "skin": "#c78d66", "metal": "#aab2c4"},
    {"name": "bone", "bg": "#15130f", "base": "#b5a68a", "dark": "#5b5141", "light": "#e6dcc4", "accent": "#c9854f", "skin": "#c9946d", "metal": "#9da3a8"},
    {"name": "crimson", "bg": "#160d0e", "base": "#7d2f35", "dark": "#3d171b", "light": "#c76a6a", "accent": "#e0b15a", "skin": "#c58a64", "metal": "#a2a6ae"},
    {"name": "moss", "bg": "#11150d", "base": "#5b6b34", "dark": "#2d3518", "light": "#a4b86a", "accent": "#d6a85a", "skin": "#c38d66", "metal": "#9fa6a0"},
]


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    ca, cb = _rgb(a), _rgb(b)
    return tuple(int(ca[i] * (1 - t) + cb[i] * t) for i in range(3))  # type: ignore[return-value]


def _shade(color: str, factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in _rgb(color))  # type: ignore[return-value]


def _palette(asset: dict[str, Any], seed_text: str) -> dict[str, str]:
    requested = asset.get("palette")
    if isinstance(requested, str):
        for palette in PALETTES:
            if palette["name"] == requested:
                return dict(palette)
    if isinstance(requested, dict) and requested.get("base"):
        base = str(requested["base"])
        return {
            "name": "custom",
            "bg": str(requested.get("bg", "#14110d")),
            "base": base,
            "dark": str(requested.get("dark", "#3a2419")),
            "light": str(requested.get("light", "#d29a68")),
            "accent": str(requested.get("accent", "#e6b45a")),
            "skin": str(requested.get("skin", "#c98d64")),
            "metal": str(requested.get("metal", "#9aa3ad")),
        }
    index = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16) % len(PALETTES)
    return dict(PALETTES[index])


def _font(size: int, bold: bool = False) -> Any:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow without sized default font
        return ImageFont.load_default()


def _downsample(image: Any, size: tuple[int, int]) -> Any:
    return image.resize(size, Image.Resampling.LANCZOS)


def _gradient(size: tuple[int, int], top: str, bottom: str) -> Any:
    width, height = size
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels[0, y] = _mix(top, bottom, t)
    return strip.resize((width, height))


def _draw_pawn(size: tuple[int, int], palette: dict[str, str], direction: str, rng: random.Random) -> Any:
    scale = SUPERSAMPLE
    width, height = size[0] * scale, size[1] * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = palette["dark"]
    line = max(2, int(width * 0.010))
    cx, ground = width * 0.5, height * 0.88

    # Ground shadow
    draw.ellipse([cx - width * 0.24, ground - height * 0.07, cx + width * 0.24, ground + height * 0.02], fill=(0, 0, 0, 80))

    # Legs
    leg_w, leg_h = width * 0.105, height * 0.19
    for dx in (-width * 0.085, width * 0.085):
        draw.rounded_rectangle(
            [cx + dx - leg_w / 2, ground - leg_h, cx + dx + leg_w / 2, ground],
            radius=leg_w * 0.38, fill=palette["dark"], outline=outline, width=line,
        )
        draw.rounded_rectangle(
            [cx + dx - leg_w * 0.55, ground - leg_h * 0.18, cx + dx + leg_w * 0.55, ground],
            radius=leg_w * 0.25, fill=palette["metal"], outline=outline, width=max(1, line // 2),
        )

    # Torso and belt
    body_w, body_h = width * 0.36, height * 0.30
    body_top, body_bottom = height * 0.47, height * 0.76
    draw.rounded_rectangle(
        [cx - body_w / 2, body_top, cx + body_w / 2, body_bottom],
        radius=body_w * 0.26, fill=palette["base"], outline=outline, width=line,
    )
    draw.rectangle([cx - body_w / 2, body_bottom - height * 0.055, cx + body_w / 2, body_bottom - height * 0.025],
                   fill=palette["accent"], outline=outline, width=max(1, line // 2))

    # Arms
    arm_w = width * 0.078
    for side in (-1, 1):
        ax = cx + side * body_w * 0.58
        draw.rounded_rectangle(
            [ax - arm_w / 2, body_top + height * 0.02, ax + arm_w / 2, body_bottom - height * 0.02],
            radius=arm_w * 0.5, fill=palette["skin"], outline=outline, width=line,
        )
        draw.rounded_rectangle(
            [ax - arm_w * 0.62, body_bottom - height * 0.075, ax + arm_w * 0.62, body_bottom - height * 0.025],
            radius=arm_w * 0.3, fill=palette["dark"], outline=outline, width=max(1, line // 2),
        )

    # Neck and collar sit between torso and head
    draw.rectangle([cx - width * 0.035, body_top - height * 0.045, cx + width * 0.035, body_top + height * 0.035],
                   fill=palette["skin"], outline=outline, width=max(1, line // 2))
    draw.rounded_rectangle([cx - body_w * 0.30, body_top - height * 0.010, cx + body_w * 0.30, body_top + height * 0.038],
                           radius=width * 0.012, fill=palette["light"], outline=outline, width=max(1, line // 2))

    # Chest strap and both shoulder pads
    draw.line([cx - body_w * 0.38, body_top + height * 0.055, cx + body_w * 0.34, body_bottom - height * 0.055],
              fill=palette["accent"], width=max(2, int(width * 0.018)))
    for side in (-1, 1):
        draw.rounded_rectangle([cx + side * body_w * 0.56 - body_w * 0.10, body_top + height * 0.008,
                                cx + side * body_w * 0.56 + body_w * 0.10, body_top + height * 0.058],
                               radius=width * 0.012, fill=palette["dark"], outline=outline, width=max(1, line // 2))

    # Head and hair
    head_r, head_y = width * 0.135, height * 0.355
    draw.ellipse([cx - head_r, head_y - head_r, cx + head_r, head_y + head_r],
                 fill=palette["skin"], outline=outline, width=line)
    if direction == "north":
        draw.ellipse([cx - head_r * 0.98, head_y - head_r * 1.02, cx + head_r * 0.98, head_y + head_r * 0.45],
                     fill=palette["dark"], outline=outline, width=max(1, line // 2))
    else:
        draw.arc([cx - head_r, head_y - head_r * 1.08, cx + head_r, head_y + head_r * 0.82],
                 180, 360, fill=palette["dark"], width=int(head_r * 0.52))

    if direction == "south":
        for side in (-1, 1):
            eye_x = cx + side * head_r * 0.34
            draw.ellipse([eye_x - head_r * 0.10, head_y - head_r * 0.08, eye_x + head_r * 0.10, head_y + head_r * 0.12],
                         fill=outline)
        draw.line([cx - head_r * 0.16, head_y + head_r * 0.42, cx + head_r * 0.16, head_y + head_r * 0.42],
                  fill=outline, width=max(1, line // 2))
    elif direction in ("east", "west"):
        # Profile nose and one visible eye
        draw.polygon([(cx + head_r * 0.55, head_y - head_r * 0.05),
                      (cx + head_r * 1.05, head_y + head_r * 0.14),
                      (cx + head_r * 0.55, head_y + head_r * 0.30)],
                     fill=palette["skin"], outline=outline)
        draw.ellipse([cx + head_r * 0.10, head_y - head_r * 0.20, cx + head_r * 0.32, head_y + head_r * 0.02],
                     fill=outline)

    # Compact rifle silhouette for profile views
    if direction in ("east", "west"):
        start = (cx - body_w * 0.78, body_bottom - height * 0.13)
        end = (cx + body_w * 1.02, body_top + height * 0.02)
        draw.line([start, end], fill=outline, width=int(width * 0.042), joint="curve")
        draw.line([start, end], fill=palette["metal"], width=int(width * 0.022), joint="curve")
        draw.polygon([(start[0] - width * 0.03, start[1] + height * 0.035),
                      (start[0] + width * 0.08, start[1] + height * 0.075),
                      (start[0] + width * 0.10, start[1] - height * 0.010),
                      (start[0] - width * 0.01, start[1] - height * 0.025)],
                     fill=palette["base"], outline=outline)
        mid = (cx - body_w * 0.05, body_bottom - height * 0.01)
        draw.rounded_rectangle([mid[0] - width * 0.022, mid[1], mid[0] + width * 0.022, mid[1] + height * 0.085],
                               radius=width * 0.010, fill=palette["dark"], outline=outline, width=max(1, line // 2))

    # Shoulder accent + belt buckle
    draw.rounded_rectangle([cx - body_w * 0.55, body_top + height * 0.012, cx - body_w * 0.34, body_top + height * 0.055],
                           radius=width * 0.012, fill=palette["accent"], outline=outline, width=max(1, line // 2))
    draw.rectangle([cx - width * 0.022, body_bottom - height * 0.052, cx + width * 0.022, body_bottom - height * 0.028],
                   fill=palette["light"], outline=outline, width=max(1, line // 2))

    if direction == "west":
        image = ImageOps.mirror(image)
    return _downsample(image, size)


def _draw_item(size: tuple[int, int], palette: dict[str, str], kind: str, rng: random.Random) -> Any:
    scale = SUPERSAMPLE
    width, height = size[0] * scale, size[1] * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = palette["dark"]
    line = max(2, int(width * 0.012))

    if kind in ("apparel", "armor"):
        # A simple cloak/jacket silhouette
        draw.polygon([(width * 0.30, height * 0.20), (width * 0.70, height * 0.20),
                      (width * 0.84, height * 0.82), (width * 0.50, height * 0.72),
                      (width * 0.16, height * 0.82)], fill=palette["base"], outline=outline)
        draw.polygon([(width * 0.38, height * 0.20), (width * 0.62, height * 0.20),
                      (width * 0.56, height * 0.52), (width * 0.44, height * 0.52)], fill=palette["light"], outline=outline)
        draw.line([width * 0.50, height * 0.42, width * 0.50, height * 0.72], fill=palette["accent"], width=line * 2)
        draw.rounded_rectangle([width * 0.30, height * 0.62, width * 0.70, height * 0.68],
                               radius=height * 0.015, fill=palette["dark"], outline=outline, width=line)
        return _downsample(image, size)

    if kind in ("item", "resource"):
        # A strapped crate
        draw.rounded_rectangle([width * 0.18, height * 0.22, width * 0.82, height * 0.82],
                               radius=width * 0.04, fill=palette["base"], outline=outline, width=line)
        for offset in (0.35, 0.55, 0.75):
            draw.line([width * 0.18, height * offset, width * 0.82, height * offset],
                      fill=palette["dark"], width=max(2, int(width * 0.012)))
        draw.line([width * 0.30, height * 0.22, width * 0.30, height * 0.82], fill=palette["accent"], width=line * 2)
        draw.line([width * 0.70, height * 0.22, width * 0.70, height * 0.82], fill=palette["accent"], width=line * 2)
        draw.rounded_rectangle([width * 0.42, height * 0.46, width * 0.58, height * 0.58],
                               radius=width * 0.01, fill=palette["metal"], outline=outline, width=max(1, line // 2))
        return _downsample(image, size)

    # Default: a compact rifle/tool on a diagonal
    start = (width * 0.16, height * 0.80)
    end = (width * 0.84, height * 0.20)
    draw.line([start, end], fill=outline, width=int(width * 0.105), joint="curve")
    draw.line([start, end], fill=palette["metal"], width=int(width * 0.058), joint="curve")
    draw.line([(width * 0.25, height * 0.70), (width * 0.70, height * 0.30)],
              fill=palette["light"], width=max(2, int(width * 0.012)))

    # Stock, grip and magazine
    draw.polygon([(width * 0.12, height * 0.78), (width * 0.30, height * 0.90),
                  (width * 0.38, height * 0.82), (width * 0.22, height * 0.70)],
                 fill=palette["base"], outline=outline)
    draw.rounded_rectangle([width * 0.42, height * 0.60, width * 0.54, height * 0.78],
                           radius=width * 0.02, fill=palette["dark"], outline=outline, width=max(1, line // 2))
    draw.rounded_rectangle([width * 0.54, height * 0.48, width * 0.62, height * 0.66],
                           radius=width * 0.015, fill=palette["base"], outline=outline, width=max(1, line // 2))
    draw.line([width * 0.58, height * 0.28, width * 0.78, height * 0.34],
              fill=palette["accent"], width=max(2, int(width * 0.018)))
    draw.ellipse([width * 0.76, height * 0.18, width * 0.84, height * 0.26],
                 fill=palette["accent"], outline=outline, width=max(1, line // 2))
    return _downsample(image, size)


def _draw_building(size: tuple[int, int], palette: dict[str, str], rng: random.Random) -> Any:
    scale = SUPERSAMPLE
    width, height = size[0] * scale, size[1] * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = palette["dark"]
    line = max(2, int(width * 0.012))

    # Table shadow and frame
    draw.rounded_rectangle([width * 0.07, height * 0.12, width * 0.93, height * 0.90],
                           radius=width * 0.05, fill=palette["dark"], outline=outline, width=line)
    draw.rounded_rectangle([width * 0.12, height * 0.18, width * 0.88, height * 0.80],
                           radius=width * 0.03, fill=palette["base"], outline=outline, width=line)

    # Plank lines
    for y in (0.30, 0.42, 0.54, 0.66, 0.78):
        draw.line([width * 0.14, height * y, width * 0.86, height * y],
                  fill=palette["dark"], width=max(1, int(width * 0.006)))

    # Metal vise on the left
    draw.rounded_rectangle([width * 0.18, height * 0.26, width * 0.36, height * 0.44],
                           radius=width * 0.015, fill=palette["metal"], outline=outline, width=line)
    draw.rounded_rectangle([width * 0.21, height * 0.31, width * 0.33, height * 0.39],
                           radius=width * 0.01, fill=palette["dark"], outline=outline, width=max(1, line // 2))
    draw.line([width * 0.27, height * 0.44, width * 0.27, height * 0.58], fill=palette["metal"], width=line * 2)

    # Hammer and saw on the right
    draw.line([width * 0.62, height * 0.30, width * 0.80, height * 0.52],
              fill=palette["dark"], width=line * 2)
    draw.rounded_rectangle([width * 0.74, height * 0.24, width * 0.86, height * 0.34],
                           radius=width * 0.01, fill=palette["metal"], outline=outline, width=max(1, line // 2))
    draw.polygon([(width * 0.58, height * 0.58), (width * 0.84, height * 0.58),
                  (width * 0.80, height * 0.68), (width * 0.62, height * 0.68)],
                 fill=palette["light"], outline=outline)

    # Accent stripe and bolts
    draw.rectangle([width * 0.14, height * 0.72, width * 0.86, height * 0.745], fill=palette["accent"])
    for bx, by in ((0.16, 0.22), (0.84, 0.22), (0.16, 0.76), (0.84, 0.76)):
        draw.ellipse([width * bx - width * 0.018, height * by - width * 0.018,
                      width * bx + width * 0.018, height * by + width * 0.018],
                     fill=palette["light"], outline=outline, width=max(1, line // 2))

    # Sparse grain so the flat fill does not look like plastic
    for _ in range(160):
        x = rng.uniform(width * 0.13, width * 0.87)
        y = rng.uniform(height * 0.19, height * 0.79)
        draw.point((x, y), fill=palette["dark"])
    return _downsample(image, size)


def _draw_icon(size: tuple[int, int], palette: dict[str, str], rng: random.Random) -> Any:
    scale = SUPERSAMPLE
    width, height = size[0] * scale, size[1] * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = palette["dark"]
    line = max(2, int(width * 0.016))

    cx, cy, radius = width * 0.5, height * 0.5, width * 0.40
    points = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=palette["base"], outline=outline)
    draw.polygon([(x * 0.92 + cx * 0.08, y * 0.92 + cy * 0.08) for x, y in points],
                 fill=palette["dark"], outline=outline)

    # Gear-like inner emblem
    draw.ellipse([cx - radius * 0.48, cy - radius * 0.48, cx + radius * 0.48, cy + radius * 0.48],
                 fill=palette["accent"], outline=outline, width=max(1, line // 2))
    draw.ellipse([cx - radius * 0.20, cy - radius * 0.20, cx + radius * 0.20, cy + radius * 0.20],
                 fill=palette["bg"], outline=outline, width=max(1, line // 2))
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        draw.line([cx + radius * 0.30 * math.cos(rad), cy + radius * 0.30 * math.sin(rad),
                   cx + radius * 0.62 * math.cos(rad), cy + radius * 0.62 * math.sin(rad)],
                  fill=palette["light"], width=max(2, int(width * 0.025)))
    return _downsample(image, size)


def _draw_preview(size: tuple[int, int], palette: dict[str, str], title: str, subtitle: str, rng: random.Random) -> Any:
    scale = 2
    width, height = size[0] * scale, size[1] * scale
    image = _gradient((width, height), palette["bg"], palette["dark"])
    draw = ImageDraw.Draw(image, "RGBA")

    # Soft diagonal bands and a glow behind the emblem
    for offset in range(-height, width, int(width * 0.10)):
        draw.polygon([(offset, 0), (offset + width * 0.045, 0),
                      (offset + width * 0.045 + height, height), (offset + height, height)],
                     fill=(255, 255, 255, 8))
    draw.ellipse([width * 0.02, -height * 0.20, width * 0.58, height * 0.95],
                 fill=(*_rgb(palette["base"]), 55))

    # Emblem on the left
    icon_size = int(min(width, height) * 0.36)
    icon = _draw_icon((icon_size, icon_size), palette, rng)
    image.paste(icon, (int(width * 0.07), int((height - icon_size) / 2)), icon)

    # Title block on the right
    title_font = _font(int(height * 0.105), bold=True)
    subtitle_font = _font(int(height * 0.040))
    footer_font = _font(int(height * 0.030))
    max_width = width * 0.54
    lines: list[str] = []
    for word in title.split():
        if not lines:
            lines.append(word)
        elif draw.textlength(lines[-1] + " " + word, font=title_font) <= max_width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    x = int(width * 0.43)
    y = int(height * 0.30)
    for line in lines[:3]:
        draw.text((x, y), line, font=title_font, fill=_rgb(palette["light"]),
                  stroke_width=max(1, int(height * 0.003)), stroke_fill=_rgb(palette["bg"]))
        y += int(height * 0.12)
    draw.text((x, y + int(height * 0.015)), subtitle, font=subtitle_font, fill=_rgb(palette["accent"]))
    draw.line([x, y + int(height * 0.075), int(width * 0.93), y + int(height * 0.075)],
              fill=(*_rgb(palette["accent"]), 150), width=max(1, int(height * 0.004)))
    draw.text((x, int(height * 0.84)), "RimWorldForge  |  procedural art", font=footer_font,
              fill=(*_rgb(palette["light"]), 190))

    # Border
    draw.rectangle([0, 0, width - 1, height - 1], outline=(*_rgb(palette["accent"]), 120),
                   width=max(2, int(height * 0.006)))
    return _downsample(image, size)


def _target_paths(asset: dict[str, Any]) -> list[tuple[str | None, Path]]:
    target = asset.get("target")
    if not target:
        return []
    path = Path(str(target).replace("\\", "/"))
    kind = str(asset.get("kind", "item"))
    directions = [str(d) for d in (asset.get("directions") or [])]
    if kind == "pawn_directional" and directions:
        stem = path.stem
        known = ("_south", "_north", "_east", "_west")
        if stem.lower().endswith(known):
            return [(stem.lower().rsplit("_", 1)[-1], path)]
        return [(direction, path.with_name(f"{stem}_{direction}{path.suffix or '.png'}")) for direction in directions]
    return [(None, path if path.suffix else path.with_suffix(".png"))]


def _render_asset(
    asset: dict[str, Any],
    mod_name: str,
    source_root: Path,
    base_seed: str,
    direction: str | None,
    path: Path,
) -> dict[str, Any]:
    kind = str(asset.get("kind", "item"))
    canvas = asset.get("canvas") or ([640, 360] if kind == "mod_preview" else [128, 128])
    size = (int(canvas[0]), int(canvas[1]))
    seed_text = f"{base_seed}:{asset.get('id', path.stem)}:{direction or ''}"
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
    palette = _palette(asset, seed_text)

    if kind == "pawn_directional":
        image = _draw_pawn(size, palette, direction or "south", rng)
    elif kind == "building":
        image = _draw_building(size, palette, rng)
    elif kind == "ui_icon":
        image = _draw_icon(size, palette, rng)
    elif kind == "mod_preview":
        subtitle = str(asset.get("subtitle") or "RimWorld 1.6 / 1.7  |  local procedural art")
        image = _draw_preview(size, palette, mod_name, subtitle, rng)
    else:
        image = _draw_item(size, palette, kind, rng)

    if image.mode == "RGBA" and not asset.get("transparent", kind != "mod_preview"):
        # Opaque asset: put it on the palette's dark ground so it reads on any background.
        ground = Image.new("RGBA", image.size, (*_rgb(palette["bg"]), 255))
        ground.alpha_composite(image)
        image = ground.convert("RGB")

    path = source_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    return {
        "asset_id": asset.get("id") or path.stem,
        "kind": kind,
        "direction": direction,
        "path": str(path),
        "relative_path": path.relative_to(source_root).as_posix(),
        "width": size[0],
        "height": size[1],
        "palette": palette["name"],
        "sha256": sha256_file(path),
    }


def generate_assets(workspace: Path, force: bool = False, seed: str | None = None) -> dict[str, Any]:
    """Generate every missing asset declared in plans/ASSETS-NEEDED.json."""
    workspace = workspace.resolve()
    config = read_json(workspace / "forge.json")
    manifest_path = workspace / "plans" / "ASSETS-NEEDED.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Asset manifest not found: {manifest_path}. Run `rwforge generate` first.")
    manifest = read_json(manifest_path)
    source = workspace / config.get("source", "source")
    mod_name = str(config.get("name") or "RimWorldMod")
    base_seed = seed or f"{config.get('packageId', mod_name)}:{manifest.get('schema', 1)}"
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for asset in manifest.get("assets", []) or []:
        if not isinstance(asset, dict):
            continue
        for direction, relative in _target_paths(asset):
            target = source / relative
            if target.is_file() and not force:
                skipped.append({"asset_id": asset.get("id"), "path": str(target), "reason": "exists"})
                continue
            generated.append(_render_asset(asset, mod_name, source, base_seed, direction, relative))
    report = {
        "schema": 1,
        "generator": GEN_VERSION,
        "seed": base_seed,
        "generated": generated,
        "skipped": skipped,
        "file_count": len(generated),
    }
    write_json(workspace / "reports" / "assets-generated.json", report)
    return {
        "ok": True,
        "workspace": str(workspace),
        "generated": len(generated),
        "skipped": len(skipped),
        "files": [item["relative_path"] for item in generated],
        "report": str(workspace / "reports" / "assets-generated.json"),
        "note": "Procedural art is a starting asset, not visual validation. Open the PNGs and check them in game.",
    }
