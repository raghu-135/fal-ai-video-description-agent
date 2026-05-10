from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _to_ms(value) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return None
    # Heuristic: sub-10k likely seconds, otherwise milliseconds.
    return int(numeric * 1000) if numeric < 10_000 else int(numeric)


def _pick(obj: dict, keys: list[str]):
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def normalize_spans(payload: dict) -> list[dict]:
    candidates: list[dict] = []

    def add_from_iter(items: Iterable, default_track: str = "default") -> None:
        for item in items:
            if isinstance(item, dict):
                cloned = dict(item)
                cloned.setdefault("_track_hint", default_track)
                candidates.append(cloned)

    if isinstance(payload.get("spans"), list):
        add_from_iter(payload["spans"])

    if isinstance(payload.get("events"), list):
        add_from_iter(payload["events"], default_track="events")

    if isinstance(payload.get("segments"), list):
        add_from_iter(payload["segments"], default_track="segments")

    if isinstance(payload.get("span_graph"), list):
        add_from_iter(payload["span_graph"], default_track="span_graph")

    tracks = payload.get("tracks")
    if isinstance(tracks, list):
        for t in tracks:
            if not isinstance(t, dict):
                continue
            track_name = str(_pick(t, ["name", "id", "track", "label"]) or "track")
            items = _pick(t, ["spans", "events", "segments", "items"])
            if isinstance(items, list):
                add_from_iter(items, default_track=track_name)

    normalized: list[dict] = []
    for idx, item in enumerate(candidates):
        time_range = item.get("timeRange") if isinstance(item.get("timeRange"), dict) else {}
        start_raw = _pick(item, ["start_ms", "start", "start_time", "begin"])
        end_raw = _pick(item, ["end_ms", "end", "end_time", "finish"])
        if start_raw is None:
            start_raw = time_range.get("start")
        if end_raw is None:
            end_raw = time_range.get("end")
        start_ms = _to_ms(start_raw)
        end_ms = _to_ms(end_raw)

        if start_ms is None or end_ms is None:
            logger.warning("Skipping span %s due to missing/non-numeric time values", idx)
            continue
        if end_ms <= start_ms:
            logger.warning("Skipping span %s due to invalid interval [%s, %s]", idx, start_ms, end_ms)
            continue

        track = str(_pick(item, ["track", "lane", "group", "speaker", "channel", "type", "_track_hint"]) or "default")
        label = str(_pick(item, ["label", "text", "name", "type", "id"]) or f"span-{idx}")
        score_raw = _pick(item, ["score", "confidence", "probability"])
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None

        span_id = str(_pick(item, ["id", "span_id"]) or f"span-{idx}")

        metadata = {
            k: v
            for k, v in item.items()
            if k
            not in {
                "start_ms",
                "start",
                "start_time",
                "begin",
                "end_ms",
                "end",
                "end_time",
                "finish",
                "track",
                "lane",
                "group",
                "speaker",
                "channel",
                "label",
                "text",
                "name",
                "type",
                "id",
                "span_id",
                "score",
                "confidence",
                "probability",
                "_track_hint",
            }
        }

        normalized.append(
            {
                "id": span_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "track": track,
                "label": label,
                "score": score,
                "metadata": metadata,
            }
        )

    normalized.sort(key=lambda s: (s["track"], s["start_ms"], s["end_ms"], s["id"]))
    return normalized


def extract_json_object(text: str) -> dict:
    text = (text or '').strip()
    if text.startswith('```json'):
        text = text.replace('```json', '', 1).strip()
    if text.startswith('```'):
        text = text[3:].strip()
    if text.endswith('```'):
        text = text[:-3].strip()

    import json
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find('{')
    if start == -1:
        raise json.JSONDecodeError('No JSON object found', text, 0)

    depth = 0
    in_string = False
    escaped = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise json.JSONDecodeError('Incomplete JSON object', text, start)

    return json.loads(text[start:end])
