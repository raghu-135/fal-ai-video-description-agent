"""Destination photoshoot analysis.

The destination shoot remains processable raw material. This inventory records
what each source image can directly support and what variants it could produce.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .utils import IMAGE_EXTENSIONS, clamp


def image_stats(path: Path) -> dict[str, Any]:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        width, height = image.size
        thumb = image.resize((160, max(1, int(160 * height / width))))

    stat = ImageStat.Stat(thumb)
    mean = [channel / 255 for channel in stat.mean]
    stddev = [channel / 255 for channel in stat.stddev]
    brightness = sum(mean) / 3
    contrast = sum(stddev) / 3
    edges = ImageStat.Stat(thumb.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0] / 255

    pixels = list(thumb.getdata())
    total = len(pixels) or 1
    sky = 0
    green = 0
    warm = 0
    white = 0
    for r, g, b in pixels:
        rn, gn, bn = r / 255, g / 255, b / 255
        if bn > 0.45 and bn > rn * 1.08 and bn > gn * 1.03:
            sky += 1
        if gn > rn * 1.08 and gn > bn * 1.08 and gn > 0.22:
            green += 1
        if rn > 0.45 and rn > bn * 1.12 and gn > bn * 1.02:
            warm += 1
        if rn > 0.78 and gn > 0.78 and bn > 0.78:
            white += 1

    return {
        "width": width,
        "height": height,
        "brightness": round(brightness, 4),
        "contrast": round(contrast, 4),
        "edge_density": round(edges, 4),
        "sky_ratio": round(sky / total, 4),
        "green_ratio": round(green / total, 4),
        "warm_ratio": round(warm / total, 4),
        "white_ratio": round(white / total, 4),
        "orientation": "landscape" if width >= height else "portrait",
    }


def filename_number(path: Path) -> int | None:
    match = re.search(r"(\d{3,})", path.stem)
    return int(match.group(1)) if match else None


def classify_space(
    path: Path,
    non_drone_position: float,
    stats: dict[str, Any],
    *,
    use_filename_profile: bool = True,
) -> tuple[str, str, list[str]]:
    name = path.name.upper()
    number = filename_number(path)

    if name.startswith("DJI") or "DRONE" in name:
        viewpoint = "top-down drone" if stats["sky_ratio"] < 0.04 else "oblique drone"
        return "aerial", viewpoint, ["roofline", "lot", "landscaping", "neighborhood"]

    if use_filename_profile and number:
        if 2390 <= number <= 2410:
            return "entry", "eye-level wide interior", ["entry", "stairs", "arrival"]
        if 2411 <= number <= 2444:
            return "living", "eye-level wide interior", ["open plan", "windows", "seating"]
        if 2445 <= number <= 2489:
            return "kitchen", "eye-level wide or medium interior", ["island", "cabinetry", "appliances"]
        if 2490 <= number <= 2524:
            return "detail", "medium utility or detail view", ["storage", "laundry", "fixture"]
        if 2525 <= number <= 2589:
            return "bedroom", "eye-level wide interior", ["bed", "window", "private room"]
        if 2590 <= number <= 2608:
            return "bathroom", "eye-level medium interior", ["vanity", "mirror", "fixture"]
        if 2609 <= number <= 2630:
            return "garage", "wide utility view", ["garage", "storage", "utility"]
        if 2631 <= number <= 2669:
            return "amenity", "wide outdoor living view", ["patio", "outdoor living", "covered area"]
        if number >= 2670:
            return "exterior", "ground-level wide exterior", ["front elevation", "yard", "landscaping"]

    outdoor_score = stats["sky_ratio"] + stats["green_ratio"] * 0.85
    if outdoor_score > 0.46:
        return "exterior", "ground-level wide exterior", ["front elevation", "yard", "landscaping"]

    if non_drone_position < 0.12:
        return "entry", "eye-level wide interior", ["entry", "arrival"]
    if non_drone_position < 0.34:
        return "living", "eye-level wide interior", ["open plan", "windows"]
    if non_drone_position < 0.48:
        return "kitchen", "eye-level wide interior", ["cabinetry", "appliances"]
    if non_drone_position < 0.66:
        return "bedroom", "eye-level wide interior", ["private room", "window"]
    if non_drone_position < 0.76:
        return "bathroom", "eye-level medium interior", ["vanity", "fixture"]
    if non_drone_position < 0.88:
        return "amenity", "wide amenity view", ["utility", "outdoor living"]
    return "exterior", "ground-level wide exterior", ["yard", "front elevation"]


def infer_shot_scale(space_type: str, stats: dict[str, Any]) -> str:
    if space_type == "aerial":
        return "aerial"
    if space_type == "detail" or stats["edge_density"] > 0.18 and stats["white_ratio"] > 0.42:
        return "detail"
    if space_type in {"bathroom", "kitchen"} and stats["edge_density"] > 0.14:
        return "medium"
    if space_type in {"exterior", "living", "bedroom", "amenity", "garage"}:
        return "wide"
    return "medium"


def motion_suitability(space_type: str, shot_scale: str, stats: dict[str, Any]) -> dict[str, float]:
    base = {
        "dolly_in": 0.45,
        "truck_right": 0.45,
        "orbit": 0.25,
        "crane_up": 0.25,
        "detail_push": 0.25,
        "drone": 0.05,
        "static": 0.8,
    }
    if space_type == "aerial":
        base.update({"drone": 0.95, "crane_up": 0.75, "orbit": 0.72, "truck_right": 0.62})
    elif space_type in {"exterior", "amenity"}:
        base.update({"dolly_in": 0.65, "truck_right": 0.72, "crane_up": 0.65, "orbit": 0.46, "drone": 0.32})
    elif shot_scale == "detail":
        base.update({"detail_push": 0.9, "dolly_in": 0.58, "truck_right": 0.55})
    else:
        base.update({"dolly_in": 0.76, "truck_right": 0.78, "detail_push": 0.4})
    if stats["edge_density"] > 0.2:
        base["orbit"] = max(0.1, base["orbit"] - 0.12)
    return {key: round(clamp(value), 3) for key, value in base.items()}


def variant_potential(space_type: str, shot_scale: str) -> list[str]:
    variants = ["raw_passthrough", "conservative_edit"]
    if space_type not in {"aerial", "garage"}:
        variants.append("cinematic_light_variant")
    if space_type != "aerial":
        variants.append("detail_crop")
    if space_type in {"exterior", "aerial", "amenity"}:
        variants.append("first_last_frame_pair")
    if shot_scale in {"wide", "aerial"}:
        variants.append("creative_reframe")
    return variants


def analyze_photoshoot(folder: Path, *, use_filename_profile: bool = True) -> dict[str, Any]:
    paths = sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths:
        raise SystemExit(f"No supported images found in {folder}")

    non_drone_paths = [path for path in paths if not path.name.upper().startswith("DJI")]
    non_drone_indexes = {path: index for index, path in enumerate(non_drone_paths)}
    assets = []
    for index, path in enumerate(paths):
        stats = image_stats(path)
        nd_index = non_drone_indexes.get(path)
        nd_position = nd_index / max(1, len(non_drone_paths) - 1) if nd_index is not None else 0
        space_type, viewpoint, features = classify_space(
            path,
            nd_position,
            stats,
            use_filename_profile=use_filename_profile,
        )
        shot_scale = infer_shot_scale(space_type, stats)
        aesthetic_quality = clamp(
            0.25
            + stats["brightness"] * 0.28
            + stats["contrast"] * 0.9
            + stats["edge_density"] * 0.8
            - abs(stats["brightness"] - 0.62) * 0.22
        )
        assets.append(
            {
                "id": f"asset_{index + 1:03d}",
                "path": str(path),
                "filename": path.name,
                "spaceType": space_type,
                "shotScale": shot_scale,
                "viewpoint": viewpoint,
                "featureTags": features,
                "compositionQuality": "strong" if aesthetic_quality > 0.62 else "acceptable" if aesthetic_quality > 0.48 else "weak",
                "geometry": {
                    "orientation": stats["orientation"],
                    "perspectiveRisk": "medium" if stats["edge_density"] > 0.2 else "low",
                    "lineQuality": "busy" if stats["edge_density"] > 0.18 else "clean",
                },
                "lightingPotential": {
                    "brightness": stats["brightness"],
                    "contrast": stats["contrast"],
                    "skyRatio": stats["sky_ratio"],
                    "greenRatio": stats["green_ratio"],
                    "timelapsePotential": "high" if stats["sky_ratio"] > 0.09 else "medium" if stats["brightness"] > 0.58 else "low",
                },
                "motionSuitability": motion_suitability(space_type, shot_scale, stats),
                "variantPotential": variant_potential(space_type, shot_scale),
                "aestheticQuality": round(aesthetic_quality, 3),
                "stats": stats,
            }
        )

    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset["spaceType"]] = counts.get(asset["spaceType"], 0) + 1

    return {
        "schema": "photo_inventory.local.v1",
        "sourceFolder": str(folder),
        "assetCount": len(assets),
        "spaceTypeCounts": counts,
        "sourceAssets": assets,
        "analysisNotes": [
            "local MVP inventory uses image statistics and filename ordering",
            "destination photos are still processable: every asset carries variantPotential",
            "replace local labels with multimodal image understanding for production",
            "filename profile disabled for generic uploads" if not use_filename_profile else "filename profile enabled",
        ],
    }
