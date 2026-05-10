"""Normalize model shot spans against deterministic cut candidates."""

from __future__ import annotations

import copy
from typing import Any


def granular_shot_spans(
    parsed_span_graph: dict[str, Any],
    *,
    duration_seconds: float,
    cut_candidates: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Return shot-level spans without assuming the model found every cut.

    If the model already produced a rich shot graph, keep it. If it collapsed
    the reference into broad montage shots, split against deterministic cut
    candidates and use the model spans as semantic parents.
    """
    spans = parsed_span_graph.get("span_graph", [])
    shots = [span for span in spans if isinstance(span, dict) and span.get("type") == "shot"]
    shots = sorted(shots, key=time_start)
    cuts = clean_cuts(cut_candidates, duration_seconds)
    if not cuts:
        return shots
    expected_segments = len(cuts) + 1
    if len(shots) >= max(12, int(expected_segments * 0.65)):
        return shots
    return expand_from_cuts(shots, cuts, duration_seconds)


def expand_from_cuts(shots: list[dict[str, Any]], cuts: list[float], duration_seconds: float) -> list[dict[str, Any]]:
    boundaries = [0.0, *cuts, duration_seconds]
    expanded = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        if end - start < 0.25:
            continue
        parent = best_parent_span(shots, start, end)
        if parent:
            span = copy.deepcopy(parent)
            parent_id = parent.get("id")
        else:
            span = empty_span()
            parent_id = None
        span["id"] = f"cut_shot_{index:03d}"
        span["type"] = "shot"
        span["timeRange"] = {"start": round(start, 3), "end": round(end, 3)}
        span["parentCoarseShotId"] = parent_id
        span["summary"] = cut_summary(span, parent_id)
        span["notes"] = append_note(
            span.get("notes"),
            "Shot span expanded from deterministic cut candidates because the model returned a coarse shot graph.",
        )
        if parent_id:
            parents = span.get("parentIds") if isinstance(span.get("parentIds"), list) else []
            span["parentIds"] = [*parents, parent_id] if parent_id not in parents else parents
        expanded.append(span)
    return expanded


def best_parent_span(shots: list[dict[str, Any]], start: float, end: float) -> dict[str, Any] | None:
    best = None
    best_overlap = 0.0
    for shot in shots:
        shot_start, shot_end = span_bounds(shot)
        overlap = max(0.0, min(end, shot_end) - max(start, shot_start))
        if overlap > best_overlap:
            best = shot
            best_overlap = overlap
    if best:
        return best
    midpoint = (start + end) / 2
    return min(shots, key=lambda shot: abs(((span_bounds(shot)[0] + span_bounds(shot)[1]) / 2) - midpoint), default=None)


def clean_cuts(cut_candidates: list[float] | None, duration_seconds: float) -> list[float]:
    if not isinstance(cut_candidates, list):
        return []
    cleaned = sorted({round(float(cut), 3) for cut in cut_candidates if isinstance(cut, (int, float))})
    return [cut for cut in cleaned if 0.25 < cut < duration_seconds - 0.25]


def span_bounds(span: dict[str, Any]) -> tuple[float, float]:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    start = float(time_range.get("start") or 0.0)
    end = float(time_range.get("end") or start)
    return start, end


def time_start(span: dict[str, Any]) -> float:
    return span_bounds(span)[0]


def cut_summary(span: dict[str, Any], parent_id: Any) -> str:
    summary = span.get("summary")
    if isinstance(summary, str) and summary.strip():
        return f"Cut-level segment from {parent_id}: {summary}" if parent_id else summary
    return f"Cut-level reference shot segment from {parent_id or 'deterministic cut candidates'}."


def append_note(existing: Any, note: str) -> str:
    if isinstance(existing, str) and existing.strip():
        return existing.strip() + " " + note
    return note


def empty_span() -> dict[str, Any]:
    return {
        "content": {
            "spaceType": "unknown",
            "visibleFeatures": [],
            "shotScale": "unknown",
            "viewpoint": None,
        },
        "style": {
            "stylisticFunction": "unknown",
            "cameraMotion": None,
            "compositionIntent": None,
            "lightingMotion": None,
            "visualTreatment": None,
            "transitionIn": None,
            "transitionOut": "cut",
            "energyLevel": "unknown",
        },
        "transferability": "adaptable_content",
        "confidence": 0.4,
    }
