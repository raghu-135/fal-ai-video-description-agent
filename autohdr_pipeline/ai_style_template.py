"""Build a StyleTemplate from an AI-extracted span graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .segment_style_fragments import fragment_for_span
from .shot_spans import granular_shot_spans
from .style_template import build_local_style_template
from .utils import probe_video


SPACE_TYPES = {
    "exterior",
    "aerial",
    "entry",
    "living",
    "kitchen",
    "dining",
    "bedroom",
    "bathroom",
    "office",
    "hallway",
    "amenity",
    "detail",
}


def build_ai_style_template(
    parsed_span_graph: dict[str, Any],
    reference_video: Path,
    max_shots: int | None = None,
    shot_style_fragments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert model-returned spans into a compiler-ready StyleTemplate.

    The model provides semantic spans. Deterministic video metadata remains the
    source of truth for duration, so model timestamps are rescaled/clipped before
    becoming shot slots.
    """
    fallback = build_local_style_template(reference_video)
    metadata = probe_video(reference_video)
    deterministic_duration = float(metadata.get("duration_seconds") or fallback["referenceVideo"]["duration_seconds"] or 0)
    model_duration = model_duration_seconds(parsed_span_graph) or deterministic_duration
    scale = deterministic_duration / model_duration if model_duration else 1.0

    spans = parsed_span_graph.get("span_graph", [])
    shots = granular_shot_spans(
        parsed_span_graph,
        duration_seconds=deterministic_duration,
        cut_candidates=metadata.get("cut_candidates_seconds") if isinstance(metadata.get("cut_candidates_seconds"), list) else None,
    )
    selected = select_shots(shots, scale, deterministic_duration, max_shots)
    if len(selected) < 6:
        return fallback

    shot_slots = []
    cursor = 0.0
    for index, span in enumerate(selected, 1):
        original = span.get("timeRange", {})
        scaled_start, scaled_end = scaled_time_range(span, scale, deterministic_duration)
        duration = round(max(0.5, scaled_end - scaled_start), 3)
        start = round(cursor, 3)
        end = round(cursor + duration, 3)
        cursor = end
        style = span.get("style", {}) if isinstance(span.get("style"), dict) else {}
        content = span.get("content", {}) if isinstance(span.get("content"), dict) else {}
        stylistic_function = clean_string(style.get("stylisticFunction"), "unknown")
        space_type = normalize_space_type(content.get("spaceType"), stylistic_function)
        shot_scale = clean_string(content.get("shotScale"), default_shot_scale(space_type))
        camera_motion = camera_from_text(clean_string(style.get("cameraMotion"), "unknown"))
        variant = preferred_variant(stylistic_function, space_type, shot_scale)
        visual_treatment = clean_string(style.get("visualTreatment"), "cinematic neutral architectural treatment")

        slot = {
            "id": f"ai_shot_{index:03d}",
            "sourceSpanId": span.get("id"),
            "referenceTimeRange": {"start": round(scaled_start, 3), "end": round(scaled_end, 3)},
            "modelTimeRange": original,
            "timeRange": {"start": start, "end": end, "duration": duration},
            "stylisticFunction": stylistic_function,
            "musicAnchor": {"type": "beat", "timestamp": end, "lockToBeat": True},
            "contentTarget": {
                "spaceType": space_type,
                "featureTags": content.get("visibleFeatures") if isinstance(content.get("visibleFeatures"), list) else [],
                "transferability": span.get("transferability") or "adaptable_content",
                "substitutionNotes": "Preserve stylistic function before literal reference content.",
            },
            "compositionIntent": {
                "shotScale": shot_scale,
                "viewpoint": clean_string(content.get("viewpoint"), None),
                "framing": clean_string(style.get("compositionIntent"), span.get("summary") or "real estate style shot"),
                "lensFeel": "architectural lens; preserve verticals and room geometry",
            },
            "cameraMotion": camera_motion,
            "lightingMotion": {
                "type": clean_string(style.get("lightingMotion"), "none"),
                "notes": "AI-extracted lighting hint; keep edits factual.",
            },
            "visualTreatment": {
                "color": visual_treatment,
                "contrast": "contrast-rich but readable",
                "whiteBalance": "neutral",
                "shadowStrategy": "deep but not underexposed",
            },
            "transitionOut": {"type": clean_string(style.get("transitionOut"), "cut"), "notes": "AI-extracted transition hint."},
            "preferredVariantMode": variant,
            "confidence": span.get("confidence"),
            "sourceSummary": span.get("summary"),
        }
        slot["spanContext"] = aggregate_span_context(
            parsed_span_graph,
            scaled_start,
            scaled_end,
            scale,
            deterministic_duration,
            source_span_id=span.get("id"),
        )
        apply_segment_style_enrichment(slot, fragment_for_span(shot_style_fragments, span.get("id")))
        slot["creativeEvents"] = infer_creative_events(slot)
        shot_slots.append(slot)

    template = {
        **fallback,
        "schema": "style_template.ai_span_graph.v1",
        "id": "ai_extracted_reference_style",
        "referenceVideo": metadata,
        "globalStyle": merge_global_style(fallback["globalStyle"], parsed_span_graph),
        "spanGraph": spans,
        "shotSlots": shot_slots,
        "aiExtraction": {
            "modelEstimatedDurationSeconds": model_duration,
            "deterministicDurationSeconds": deterministic_duration,
            "timestampScaleApplied": round(scale, 6),
            "inputSpanCount": len(spans) if isinstance(spans, list) else None,
            "modelShotSpanCount": sum(1 for span in spans if isinstance(span, dict) and span.get("type") == "shot")
            if isinstance(spans, list)
            else None,
            "granularShotSpanCount": len(shots),
            "selectedShotCount": len(shot_slots),
            "shotStyleFragmentCount": count_fragments(shot_style_fragments),
            "notes": [
                "AI spans are semantic; deterministic duration/cuts should remain source of truth.",
                "Shot slots are selected from granular shot spans. If the model returned coarse shots, deterministic cut candidates expand the timeline.",
                "Shot slot durations preserve the reference timing and are not compressed to a fixed teaser length.",
                "When present, shotStyleFragments are produced by the second per-segment prompt and merged into shot prompts.",
            ],
        },
    }
    return template


def aggregate_span_context(
    parsed_span_graph: dict[str, Any],
    start: float,
    end: float,
    scale: float,
    duration: float,
    *,
    source_span_id: Any,
) -> dict[str, Any]:
    spans = parsed_span_graph.get("span_graph")
    boundaries = parsed_span_graph.get("important_boundaries")
    overlapping = []
    if isinstance(spans, list):
        for span in spans:
            if not isinstance(span, dict) or span.get("id") == source_span_id:
                continue
            span_type = span.get("type")
            if span_type == "shot":
                continue
            span_start, span_end = scaled_time_range(span, scale, duration)
            overlap = max(0.0, min(end, span_end) - max(start, span_start))
            if overlap <= 0:
                continue
            overlapping.append(
                {
                    "id": span.get("id"),
                    "type": span_type,
                    "timeRange": {"start": round(span_start, 3), "end": round(span_end, 3)},
                    "overlapSeconds": round(overlap, 3),
                    "startsInsideShot": start <= span_start <= end,
                    "endsInsideShot": start <= span_end <= end,
                    "summary": span.get("summary"),
                    "style": span.get("style") if isinstance(span.get("style"), dict) else None,
                    "transferability": span.get("transferability"),
                }
            )

    events = []
    if isinstance(boundaries, list):
        for boundary in boundaries:
            if not isinstance(boundary, dict):
                continue
            timestamp = boundary.get("timestamp")
            if not isinstance(timestamp, (int, float)):
                continue
            scaled = max(0.0, min(duration, float(timestamp) * scale))
            if start - 0.35 <= scaled <= end + 0.35:
                events.append(
                    {
                        "timestamp": round(scaled, 3),
                        "relativeToShotStart": round(scaled - start, 3),
                        "boundaryType": boundary.get("boundaryType"),
                        "description": boundary.get("description"),
                        "confidence": boundary.get("confidence"),
                        "insideShot": start <= scaled <= end,
                    }
                )

    phrase_events = []
    for span in overlapping:
        if span.get("type") != "music_phrase":
            continue
        span_range = span["timeRange"]
        if span.get("startsInsideShot"):
            phrase_events.append(
                {
                    "type": "music_phrase_start",
                    "timestamp": span_range["start"],
                    "relativeToShotStart": round(span_range["start"] - start, 3),
                    "sourceSpanId": span["id"],
                    "summary": span.get("summary"),
                }
            )
        if span.get("endsInsideShot"):
            phrase_events.append(
                {
                    "type": "music_phrase_end",
                    "timestamp": span_range["end"],
                    "relativeToShotStart": round(span_range["end"] - start, 3),
                    "sourceSpanId": span["id"],
                    "summary": span.get("summary"),
                }
            )

    return {
        "overlappingSpans": sorted(overlapping, key=lambda item: (str(item.get("type")), item["timeRange"]["start"])),
        "boundaryEvents": sorted(events, key=lambda item: item["timestamp"]),
        "phraseEvents": sorted(phrase_events, key=lambda item: item["timestamp"]),
        "compilerNotes": summarize_span_context(overlapping, events, phrase_events),
    }


def summarize_span_context(
    overlapping: list[dict[str, Any]],
    events: list[dict[str, Any]],
    phrase_events: list[dict[str, Any]],
) -> list[str]:
    notes = []
    for span in overlapping:
        span_type = span.get("type")
        if span_type in {"music_phrase", "transition", "micro_event", "shot_group"}:
            summary = span.get("summary")
            if isinstance(summary, str) and summary.strip():
                notes.append(f"Overlaps {span_type}: {summary.strip()}")
    for event in phrase_events:
        summary = event.get("summary")
        notes.append(f"{event['type']} at +{event['relativeToShotStart']}s: {summary or event.get('sourceSpanId')}")
    for event in events:
        description = event.get("description")
        if isinstance(description, str) and description.strip():
            notes.append(f"Boundary {event.get('boundaryType')} at +{event['relativeToShotStart']}s: {description.strip()}")
    return notes[:12]


def apply_segment_style_enrichment(slot: dict[str, Any], fragment: dict[str, Any] | None) -> None:
    if not fragment:
        return
    fragment_slot = first_fragment_shot_slot(fragment)
    enrichment = {
        "fragmentId": fragment.get("id"),
        "globalStyle": fragment.get("globalStyle"),
        "audioPlan": fragment.get("audioPlan"),
        "shotSlot": fragment_slot,
        "promptFragments": fragment.get("promptFragments"),
        "creativeEvents": fragment.get("creativeEvents"),
        "qualityPolicy": fragment.get("qualityPolicy"),
        "uncertainties": fragment.get("uncertainties"),
    }
    slot["segmentStyleEnrichment"] = enrichment
    if not isinstance(fragment_slot, dict):
        return

    composition = fragment_slot.get("compositionIntent")
    if isinstance(composition, dict):
        framing = clean_string(composition.get("framing"), None)
        if framing:
            slot["compositionIntent"]["framing"] = f"{slot['compositionIntent']['framing']}. Segment-specific framing: {framing}"
        lens = clean_string(composition.get("lensFeel"), None)
        if lens:
            slot["compositionIntent"]["lensFeel"] = lens

    transition = fragment_slot.get("transitionOut")
    if isinstance(transition, dict) and clean_string(transition.get("type"), None):
        slot["transitionOut"] = transition

    prompt_plan = fragment_slot.get("promptPlan")
    if isinstance(prompt_plan, dict):
        slot["referencePromptPlan"] = prompt_plan

    quality_checks = fragment_slot.get("qualityChecks")
    if isinstance(quality_checks, list):
        slot["qualityChecksFromReference"] = [item for item in quality_checks if isinstance(item, str)]
    creative_events = fragment_slot.get("creativeEvents")
    if isinstance(creative_events, list):
        slot["fragmentCreativeEvents"] = [item for item in creative_events if isinstance(item, dict)]


def infer_creative_events(slot: dict[str, Any]) -> list[dict[str, Any]]:
    """Build loose creative payloads for model/human interpretation."""
    events = list(slot.get("fragmentCreativeEvents", [])) if isinstance(slot.get("fragmentCreativeEvents"), list) else []
    text = creative_source_text(slot)
    lowered = text.lower()
    transition = slot.get("transitionOut") if isinstance(slot.get("transitionOut"), dict) else {}
    transition_type = str(transition.get("type") or "").lower()
    transition_notes = transition.get("notes") if isinstance(transition.get("notes"), str) else None

    if any(token in lowered for token in ["season", "winter", "snow", "weather", "fall", "autumn"]):
        events.append(
            {
                "kind": "visual_transform",
                "tags": ["weather", "season", "state_change", "continuous_motion"],
                "uiLabel": "Weather/season transformation",
                "description": "The reference shot changes apparent weather or season while preserving the subject and camera motion.",
                "referenceEvidence": text[:900],
                "executionHint": {
                    "preferredStrategy": "strong_prompt_or_first_last_frame_pair",
                    "notes": "Apply as an apparent visual transition on exterior shots. Preserve the destination architecture and camera path.",
                },
            }
        )

    if any(token in lowered for token in ["furniture", "furnishing", "decor", "staging"]) and any(
        token in lowered for token in ["change", "morph", "swap", "transform", "cycle", "queued", "beat"]
    ):
        events.append(
            {
                "kind": "visual_transform",
                "tags": ["furniture", "staging", "beat_synced", "same_room"],
                "uiLabel": "Room staging transformation",
                "description": "The reference changes furnishings or room state while staying inside the same space and synced to the edit.",
                "referenceEvidence": text[:900],
                "executionHint": {
                    "preferredStrategy": "image_edit_variant_then_video_or_first_last_frame_pair",
                    "notes": "Use only a plausible styling/state change. Keep walls, windows, built-ins, fixtures, and room identity stable.",
                },
            }
        )

    if any(token in transition_type for token in ["whip", "speed", "ramp", "zoom", "flash", "match"]) or (
        transition_notes and any(token in transition_notes.lower() for token in ["whip", "speed", "ramp", "zoom", "blur", "flash", "match"])
    ):
        events.append(
            {
                "kind": "transition_execution",
                "tags": [token for token in ["whip", "speed_ramp", "zoom_blur", "match_cut", "flash"] if token.replace("_", " ") in lowered or token in lowered]
                or [transition_type or "transition"],
                "uiLabel": f"{transition.get('type') or 'Dynamic'} transition",
                "description": transition_notes or "The reference uses a dynamic camera/edit transition at this shot boundary.",
                "referenceEvidence": text[:900],
                "executionHint": {
                    "preferredStrategy": "generate_motion_tail_and_postprocess_transition",
                    "notes": "Bias the generated clip toward an energetic transition tail; assembly may add blur/speed-ramp after generation.",
                },
            }
        )

    return events


def creative_source_text(slot: dict[str, Any]) -> str:
    parts = [
        slot.get("sourceSummary"),
        slot.get("compositionIntent", {}).get("framing") if isinstance(slot.get("compositionIntent"), dict) else None,
    ]
    prompt_plan = slot.get("referencePromptPlan")
    if isinstance(prompt_plan, dict):
        parts.extend([prompt_plan.get("videoPrompt"), prompt_plan.get("modelSpecificPrompt"), prompt_plan.get("imageEditPrompt")])
    enrichment = slot.get("segmentStyleEnrichment")
    if isinstance(enrichment, dict):
        shot_slot = enrichment.get("shotSlot")
        if isinstance(shot_slot, dict):
            parts.append(jsonish(shot_slot.get("promptPlan")))
            parts.append(jsonish(shot_slot.get("transitionOut")))
            parts.append(jsonish(shot_slot.get("audioPlan")))
        parts.append(jsonish(enrichment.get("promptFragments")))
    span_context = slot.get("spanContext")
    if isinstance(span_context, dict):
        parts.append(jsonish(span_context.get("compilerNotes")))
    transition = slot.get("transitionOut")
    if isinstance(transition, dict):
        parts.append(jsonish(transition))
    return " ".join(str(part) for part in parts if part)


def jsonish(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def first_fragment_shot_slot(fragment: dict[str, Any]) -> dict[str, Any] | None:
    slots = fragment.get("shotSlots")
    if isinstance(slots, list) and slots and isinstance(slots[0], dict):
        return slots[0]
    return None


def count_fragments(fragments: dict[str, Any] | None) -> int:
    if not fragments:
        return 0
    records = fragments.get("records")
    if isinstance(records, list):
        return sum(1 for record in records if isinstance(record, dict) and isinstance(record.get("parsedFragment"), dict))
    return 0


def model_duration_seconds(parsed_span_graph: dict[str, Any]) -> float | None:
    summary = parsed_span_graph.get("video_summary")
    if isinstance(summary, dict) and isinstance(summary.get("estimated_duration_seconds"), (int, float)):
        return float(summary["estimated_duration_seconds"])
    spans = parsed_span_graph.get("span_graph")
    if not isinstance(spans, list):
        return None
    ends = []
    for span in spans:
        if isinstance(span, dict):
            time_range = span.get("timeRange")
            if isinstance(time_range, dict) and isinstance(time_range.get("end"), (int, float)):
                ends.append(float(time_range["end"]))
    return max(ends) if ends else None


def select_shots(shots: list[dict[str, Any]], scale: float, duration: float, max_shots: int | None) -> list[dict[str, Any]]:
    viable = []
    for span in shots:
        start, end = scaled_time_range(span, scale, duration)
        if end - start >= 0.5:
            viable.append(span)
    if max_shots is None:
        return viable
    if len(viable) <= max_shots:
        return viable
    if max_shots <= 1:
        return viable[:max_shots]
    stride = (len(viable) - 1) / (max_shots - 1)
    return [viable[round(i * stride)] for i in range(max_shots)]


def scaled_time_range(span: dict[str, Any], scale: float, duration: float) -> tuple[float, float]:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    start = float(time_range.get("start") or 0) * scale
    end = float(time_range.get("end") or start + 2.0) * scale
    start = max(0.0, min(duration, start))
    end = max(start + 0.5, min(duration, end))
    return start, end


def time_start(span: dict[str, Any]) -> float:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    value = time_range.get("start")
    return float(value) if isinstance(value, (int, float)) else 0.0


def clean_string(value: Any, default: str | None) -> str | None:
    if isinstance(value, str) and value.strip() and value.strip().lower() not in {"string", "null", "unknown|null"}:
        return value.strip()
    return default


def normalize_space_type(value: Any, stylistic_function: str) -> str:
    if isinstance(value, str) and value in SPACE_TYPES:
        return value
    if stylistic_function in {"establishing_hero", "property_reveal", "arrival", "closing_hero"}:
        return "exterior"
    if stylistic_function in {"texture_detail", "light_moment"}:
        return "detail"
    if stylistic_function == "amenity_proof":
        return "amenity"
    return "living"


def default_shot_scale(space_type: str) -> str:
    if space_type == "aerial":
        return "aerial"
    if space_type == "detail":
        return "detail"
    if space_type in {"bathroom", "kitchen"}:
        return "medium"
    return "wide"


def camera_from_text(text: str | None) -> dict[str, str | None]:
    lowered = (text or "").lower()
    if "drone" in lowered or "aerial" in lowered:
        movement = "drone"
    elif "truck" in lowered or "slide" in lowered or "lateral" in lowered:
        movement = "truck_right"
    elif "pull" in lowered or "dolly out" in lowered:
        movement = "pull_out"
    elif "push" in lowered or "dolly in" in lowered or "zoom" in lowered:
        movement = "push_in"
    elif "crane" in lowered or "pedestal" in lowered or "rise" in lowered:
        movement = "crane_up"
    elif "orbit" in lowered:
        movement = "orbit"
    else:
        movement = "push_in"
    speed = "fast" if "fast" in lowered else "slow" if "slow" in lowered else "medium"
    return {
        "movement_type": movement,
        "direction": text,
        "speed": speed,
        "path_shape": "arc" if movement == "orbit" else "linear",
    }


def preferred_variant(stylistic_function: str, space_type: str, shot_scale: str) -> str:
    if stylistic_function in {"light_moment", "feature_showcase", "closing_hero"}:
        return "cinematic_light_variant"
    if stylistic_function == "texture_detail" or shot_scale == "detail":
        return "detail_crop"
    if space_type in {"exterior", "amenity"}:
        return "conservative_edit"
    return "raw_passthrough"


def merge_global_style(fallback_global: dict[str, Any], parsed_span_graph: dict[str, Any]) -> dict[str, Any]:
    summary = parsed_span_graph.get("video_summary")
    if not isinstance(summary, dict):
        return fallback_global
    merged = dict(fallback_global)
    if isinstance(summary.get("dominant_style"), list):
        merged["mood"] = summary["dominant_style"]
    for source_key, target_key in [
        ("pacing_summary", "pacing"),
        ("camera_summary", "cameraGrammar"),
        ("lighting_color_summary", "lightingDoctrine"),
        ("editing_summary", "editingGrammar"),
    ]:
        value = summary.get(source_key)
        if isinstance(value, str) and value.strip():
            merged[target_key] = [value] if target_key.endswith("Grammar") or target_key.endswith("Doctrine") else value
    return merged
