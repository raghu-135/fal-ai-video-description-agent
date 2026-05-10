"""Per-shot segment style extraction using the second prompt."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .fal_tools import FalVideoUnderstandingAgent
from .prompts import SEGMENT_STYLE_PROMPT
from .shot_spans import granular_shot_spans
from .utils import probe_video, write_json


DEFAULT_FILENAME = "shot_style_fragments.json"


def extract_shot_style_fragments(
    parsed_span_graph: dict[str, Any],
    reference: Path,
    output_dir: Path,
    *,
    reference_url: str | None = None,
    endpoint: str = "openrouter/router/video",
    model: str | None = "google/gemini-3.1-pro-preview",
    max_tokens: int | None = 16000,
    temperature: float = 0.1,
    max_shots: int | None = None,
    parallelism: int = 1,
) -> dict[str, Any]:
    """Run the segment style prompt for shot spans only."""
    metadata = probe_video(reference)
    duration = float(metadata.get("duration_seconds") or 0)
    shot_spans = granular_shot_spans(
        parsed_span_graph,
        duration_seconds=duration,
        cut_candidates=metadata.get("cut_candidates_seconds") if isinstance(metadata.get("cut_candidates_seconds"), list) else None,
    )
    selected = shot_spans[:max_shots] if max_shots else shot_spans
    parallelism = len(selected) if parallelism <= 0 else parallelism
    summary = full_video_style_summary(parsed_span_graph)
    indexed_spans = list(enumerate(selected, 1))
    if parallelism > 1:
        print(f"[segment-style] parallelism={parallelism}", flush=True)
        records_by_index = {}
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {
                executor.submit(
                    extract_one_fragment,
                    parsed_span_graph,
                    span,
                    index,
                    len(selected),
                    reference,
                    reference_url,
                    endpoint,
                    model,
                    max_tokens,
                    temperature,
                    summary,
                ): index
                for index, span in indexed_spans
            }
            for future in as_completed(futures):
                index = futures[future]
                records_by_index[index] = future.result()
        records = [records_by_index[index] for index, _ in indexed_spans]
    else:
        records = [
            extract_one_fragment(
                parsed_span_graph,
                span,
                index,
                len(selected),
                reference,
                reference_url,
                endpoint,
                model,
                max_tokens,
                temperature,
                summary,
            )
            for index, span in indexed_spans
        ]

    payload = {
        "schema": "shot_style_fragments.v1",
        "sourceSpanGraphSchema": parsed_span_graph.get("schema"),
        "endpoint": endpoint,
        "model": model,
        "shotSpanCount": len(shot_spans),
        "extractedCount": len(records),
        "parallelism": parallelism,
        "records": records,
    }
    write_json(output_dir / DEFAULT_FILENAME, payload)
    return payload


def extract_one_fragment(
    parsed_span_graph: dict[str, Any],
    span: dict[str, Any],
    index: int,
    total: int,
    reference: Path,
    reference_url: str | None,
    endpoint: str,
    model: str | None,
    max_tokens: int | None,
    temperature: float,
    full_summary: str,
) -> dict[str, Any]:
    agent = FalVideoUnderstandingAgent()
    span_id = str(span.get("id") or f"shot_{index}")
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    prompt = build_segment_prompt(span, parent_context_summary(parsed_span_graph, span), full_summary)
    kwargs = {
        "endpoint": endpoint,
        "model": model,
        "system_prompt": "You are a precise real-estate video style parser. Return strict JSON only.",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "detailed_analysis": True,
    }
    result = None
    error = None
    for attempt in range(1, 4):
        try:
            result = agent.analyze_url(reference_url, prompt, **kwargs) if reference_url else agent.analyze_file(reference, prompt, **kwargs)
            error = None
            break
        except Exception as exc:  # Fal/OpenRouter can return transient upstream 500s under high fan-out.
            error = str(exc)
            if attempt < 3:
                time.sleep(2 * attempt)
    parsed = agent.parsed_output_json(result) if isinstance(result, dict) else None
    print(f"[segment-style] {index}/{total} {span_id}", flush=True)
    return {
        "spanId": span_id,
        "spanType": span.get("type"),
        "timeRange": time_range,
        "sourceSummary": span.get("summary"),
        "rawResult": result,
        "parsedFragment": parsed,
        "error": error,
    }


def load_shot_style_fragments(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"schema": "shot_style_fragments.v1", "records": []}


def build_segment_prompt(span: dict[str, Any], parent_context: str, full_summary: str) -> str:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    return (
        SEGMENT_STYLE_PROMPT.replace("{{span_id}}", str(span.get("id") or "unknown"))
        .replace("{{span_type}}", str(span.get("type") or "shot"))
        .replace("{{span_start}}", str(time_range.get("start") or 0))
        .replace("{{span_end}}", str(time_range.get("end") or 0))
        .replace("{{parent_context_summary}}", parent_context)
        .replace("{{full_video_style_summary}}", full_summary)
    )


def fragment_for_span(fragments: dict[str, Any] | None, span_id: str | None) -> dict[str, Any] | None:
    if not fragments or not span_id:
        return None
    records = fragments.get("records")
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("spanId") == span_id:
                parsed = record.get("parsedFragment")
                return parsed if isinstance(parsed, dict) else None
    parsed = fragments.get(span_id)
    return parsed if isinstance(parsed, dict) else None


def full_video_style_summary(parsed_span_graph: dict[str, Any]) -> str:
    summary = parsed_span_graph.get("video_summary")
    if not isinstance(summary, dict):
        return ""
    parts = []
    for key in ["overall_description", "pacing_summary", "editing_summary", "camera_summary", "lighting_color_summary"]:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
    dominant = summary.get("dominant_style")
    if isinstance(dominant, list):
        parts.append("dominant_style: " + ", ".join(str(item) for item in dominant))
    return "\n".join(parts)


def parent_context_summary(parsed_span_graph: dict[str, Any], span: dict[str, Any]) -> str:
    spans = parsed_span_graph.get("span_graph")
    if not isinstance(spans, list):
        return ""
    by_id = {item.get("id"): item for item in spans if isinstance(item, dict)}
    parent_ids = span.get("parentIds") if isinstance(span.get("parentIds"), list) else []
    summaries = []
    for parent_id in parent_ids:
        parent = by_id.get(parent_id)
        if isinstance(parent, dict):
            summaries.append(f"{parent_id}: {parent.get('summary')}")
    start, end = span_bounds(span)
    for item in spans:
        if not isinstance(item, dict) or item.get("type") == "shot":
            continue
        item_start, item_end = span_bounds(item)
        if max(0.0, min(end, item_end) - max(start, item_start)) <= 0:
            continue
        summary = item.get("summary")
        if isinstance(summary, str) and summary.strip():
            summaries.append(f"overlap {item.get('type')} {item_start:.3f}-{item_end:.3f}: {summary.strip()}")
    boundaries = parsed_span_graph.get("important_boundaries")
    if isinstance(boundaries, list):
        for boundary in boundaries:
            if not isinstance(boundary, dict) or not isinstance(boundary.get("timestamp"), (int, float)):
                continue
            timestamp = float(boundary["timestamp"])
            if start - 0.35 <= timestamp <= end + 0.35:
                summaries.append(
                    f"boundary {boundary.get('boundaryType')} at {timestamp:.3f} "
                    f"(shot-relative {timestamp - start:.3f}): {boundary.get('description')}"
                )
    return "\n".join(summaries[:24])


def span_bounds(span: dict[str, Any]) -> tuple[float, float]:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    start = float(time_range.get("start") or 0.0)
    end = float(time_range.get("end") or start)
    return start, end


def span_start(span: dict[str, Any]) -> float:
    time_range = span.get("timeRange") if isinstance(span.get("timeRange"), dict) else {}
    value = time_range.get("start")
    return float(value) if isinstance(value, (int, float)) else 0.0
