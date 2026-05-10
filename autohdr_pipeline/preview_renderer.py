"""Render a low-cost preview MP4 from a render plan.

This is an animatic stage, not model generation. It previews pacing, source
photo choices, substitutions, rough motion grammar, and audio timing before
spending budget on image-edit and image-to-video models.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


def render_preview(
    render_plan: dict[str, Any],
    output_path: Path,
    reference_audio: Path | None = None,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    debug_labels: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = float(render_plan["durationTarget"])
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
    ]
    if reference_audio and reference_audio.exists():
        command += ["-i", str(reference_audio), "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.3f}"]
    else:
        command += ["-an"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
    ]
    if reference_audio and reference_audio.exists():
        command += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    command.append(str(output_path))

    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for item in render_plan["timeline"]:
            for frame in shot_frames(item, width, height, fps, debug_labels):
                process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg preview render failed with exit code {return_code}")


def shot_frames(item: dict[str, Any], width: int, height: int, fps: int, debug_labels: bool):
    path = Path(item["selectedAsset"]["path"])
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    max_working_edge = int(max(width, height) * 2.25)
    if max(image.size) > max_working_edge:
        image.thumbnail((max_working_edge, max_working_edge), Image.Resampling.LANCZOS)

    duration = float(item["timeRange"]["duration"])
    frame_count = max(1, round(duration * fps))
    motion = item.get("multimodalCompilerRequest", {}).get("shotSlot", {}).get("cameraMotion", {})
    movement = motion.get("movement_type") or motion.get("movementType") or "static"
    for index in range(frame_count):
        t = index / max(1, frame_count - 1)
        eased = ease_in_out(t)
        frame = crop_motion_frame(image, width, height, movement, eased)
        frame = apply_variant_preview_grade(frame, item.get("ingredientVariantMode"))
        if debug_labels:
            frame = draw_debug_label(frame, item)
        yield frame


def crop_motion_frame(image: Image.Image, width: int, height: int, movement: str, t: float) -> Image.Image:
    src_w, src_h = image.size
    out_aspect = width / height
    if src_w / src_h > out_aspect:
        base_h = src_h
        base_w = int(base_h * out_aspect)
    else:
        base_w = src_w
        base_h = int(base_w / out_aspect)

    zoom_start, zoom_end = zoom_range_for(movement)
    zoom = zoom_start + (zoom_end - zoom_start) * t
    crop_w = max(1, int(base_w / zoom))
    crop_h = max(1, int(base_h / zoom))

    center_x = src_w / 2
    center_y = src_h / 2
    max_x = max(0, (src_w - crop_w) / 2)
    max_y = max(0, (src_h - crop_h) / 2)
    pan_x, pan_y = pan_for(movement, t)
    center_x += pan_x * max_x * 0.72
    center_y += pan_y * max_y * 0.72

    left = int(clamp(center_x - crop_w / 2, 0, src_w - crop_w))
    top = int(clamp(center_y - crop_h / 2, 0, src_h - crop_h))
    cropped = image.crop((left, top, left + crop_w, top + crop_h))
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def zoom_range_for(movement: str) -> tuple[float, float]:
    if movement in {"push_in", "dolly_in"}:
        return 1.0, 1.085
    if movement in {"pull_out", "dolly_out"}:
        return 1.085, 1.0
    if movement in {"truck_right", "truck_left", "pan"}:
        return 1.055, 1.055
    if movement in {"drone", "crane_up", "crane_down"}:
        return 1.0, 1.07
    return 1.0, 1.035


def pan_for(movement: str, t: float) -> tuple[float, float]:
    if movement == "truck_right":
        return -1 + 2 * t, 0
    if movement == "truck_left":
        return 1 - 2 * t, 0
    if movement == "crane_up":
        return 0, 0.75 - 1.5 * t
    if movement == "crane_down":
        return 0, -0.75 + 1.5 * t
    if movement == "drone":
        return -0.35 + 0.7 * t, 0.35 - 0.7 * t
    return 0, 0


def apply_variant_preview_grade(frame: Image.Image, variant_mode: str | None) -> Image.Image:
    if variant_mode == "cinematic_light_variant":
        frame = ImageEnhance.Contrast(frame).enhance(1.08)
        frame = ImageEnhance.Color(frame).enhance(1.03)
    elif variant_mode == "conservative_edit":
        frame = ImageEnhance.Contrast(frame).enhance(1.03)
    elif variant_mode == "detail_crop":
        frame = ImageEnhance.Sharpness(frame).enhance(1.12)
    return frame


def draw_debug_label(frame: Image.Image, item: dict[str, Any]) -> Image.Image:
    frame = frame.copy()
    draw = ImageDraw.Draw(frame, "RGBA")
    label = (
        f"{item['shotSlotId']} | {item['stylisticFunction']} | "
        f"{item['selectedAsset']['filename']} | {item['ingredientVariantMode']}"
    )
    font = ImageFont.load_default()
    text_box = draw.textbbox((0, 0), label, font=font)
    pad = 12
    box_w = text_box[2] - text_box[0] + pad * 2
    box_h = text_box[3] - text_box[1] + pad * 2
    draw.rectangle((20, 20, 20 + box_w, 20 + box_h), fill=(0, 0, 0, 150))
    draw.text((20 + pad, 20 + pad), label, fill=(255, 255, 255, 235), font=font)
    return frame


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def render_preview_from_file(
    render_plan_path: Path,
    output_path: Path,
    reference_audio: Path | None = None,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    debug_labels: bool = False,
) -> None:
    render_plan = json.loads(render_plan_path.read_text(encoding="utf-8"))
    render_preview(render_plan, output_path, reference_audio, width, height, fps, debug_labels)
