"""Shared utilities for the AutoHDR pipeline."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .blueprint import REFERENCE_CUT_CANDIDATES


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SCENE_THRESHOLD = 0.22
MIN_CUT_GAP_SECONDS = 0.45
MAX_CUT_CANDIDATES = 80


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def parse_frame_rate(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    numerator, denominator = rate.split("/", 1)
    try:
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None


def normalize_cut_candidates(
    candidates: list[float],
    *,
    duration: float | None,
    min_gap_seconds: float = MIN_CUT_GAP_SECONDS,
    max_candidates: int = MAX_CUT_CANDIDATES,
) -> list[float]:
    normalized: list[float] = []
    upper_bound = duration - 0.25 if duration else None
    for candidate in sorted({round(float(value), 3) for value in candidates}):
        if candidate <= 0.25:
            continue
        if upper_bound is not None and candidate >= upper_bound:
            continue
        if normalized and candidate - normalized[-1] < min_gap_seconds:
            continue
        normalized.append(candidate)

    if max_candidates > 0 and len(normalized) > max_candidates:
        if max_candidates == 1:
            return normalized[:1]
        stride = (len(normalized) - 1) / (max_candidates - 1)
        return [normalized[round(index * stride)] for index in range(max_candidates)]
    return normalized


def detect_cut_candidates(video_path: Path, duration: float | None) -> list[float]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-vf",
        f"select=gt(scene\\,{SCENE_THRESHOLD}),showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []

    raw_candidates = [float(match) for match in re.findall(r"pts_time:([0-9.]+)", result.stderr)]
    return normalize_cut_candidates(raw_candidates, duration=duration)


def probe_video(video_path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {
            "path": str(video_path),
            "duration_seconds": None,
            "width": None,
            "height": None,
            "fps": None,
            "cut_candidates_seconds": REFERENCE_CUT_CANDIDATES,
            "analysis_notes": ["ffprobe metadata unavailable; using static reference cut candidates"],
        }

    stream = next((item for item in data.get("streams", []) if "width" in item), {})
    duration = data.get("format", {}).get("duration") or stream.get("duration")
    duration_seconds = round(float(duration), 3) if duration else None
    width = stream.get("width")
    height = stream.get("height")
    cut_candidates = detect_cut_candidates(video_path, duration_seconds)
    if len(cut_candidates) >= 8:
        cut_notes = [
            f"cut candidates detected with ffmpeg scene threshold {SCENE_THRESHOLD}",
            "scene list is filtered to avoid near-duplicate cuts before model span extraction",
        ]
    else:
        cut_candidates = REFERENCE_CUT_CANDIDATES
        cut_notes = [
            "dynamic scene detection found too few cuts; using static reference cut candidates",
            "style slots are the local MVP blueprint until Fal span extraction is wired in",
        ]
    return {
        "path": str(video_path),
        "duration_seconds": duration_seconds,
        "width": width,
        "height": height,
        "fps": parse_frame_rate(stream.get("r_frame_rate")),
        "aspect_ratio": f"{width}:{height}" if width and height else None,
        "cut_candidates_seconds": cut_candidates,
        "analysis_notes": cut_notes,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
