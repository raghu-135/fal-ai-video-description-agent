"""Shared utilities for the AutoHDR pipeline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .blueprint import REFERENCE_CUT_CANDIDATES


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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
    width = stream.get("width")
    height = stream.get("height")
    return {
        "path": str(video_path),
        "duration_seconds": round(float(duration), 3) if duration else None,
        "width": width,
        "height": height,
        "fps": parse_frame_rate(stream.get("r_frame_rate")),
        "aspect_ratio": f"{width}:{height}" if width and height else None,
        "cut_candidates_seconds": REFERENCE_CUT_CANDIDATES,
        "analysis_notes": [
            "cut candidates are the rough FFmpeg scene-threshold list preserved in megaprompt.md",
            "style slots are the local MVP blueprint until Fal span extraction is wired in",
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

