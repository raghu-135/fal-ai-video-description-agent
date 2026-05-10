from src.app.ui.pages.timeline_utils import extract_json_object, normalize_spans


def test_normalize_spans_variant_keys_and_tracks():
    payload = {
        "tracks": [
            {
                "name": "speaker_a",
                "items": [
                    {"id": "a1", "begin": 1.2, "finish": 2.8, "text": "hello", "confidence": 0.9}
                ],
            }
        ],
        "events": [
            {"span_id": "e1", "start_time": 3000, "end_time": 4500, "label": "event"}
        ],
    }

    spans = normalize_spans(payload)
    assert len(spans) == 2
    assert spans[0]["id"] == "e1"
    assert spans[0]["track"] == "events"
    assert spans[1]["id"] == "a1"
    assert spans[1]["track"] == "speaker_a"
    assert spans[1]["start_ms"] == 1200
    assert spans[1]["end_ms"] == 2800
    assert spans[1]["score"] == 0.9


def test_normalize_spans_skips_invalid_values():
    payload = {
        "spans": [
            {"id": "ok", "start": 1, "end": 2},
            {"id": "bad_missing", "start": 1},
            {"id": "bad_type", "start": "x", "end": 2},
            {"id": "bad_range", "start": 10, "end": 5},
        ]
    }

    spans = normalize_spans(payload)
    assert [s["id"] for s in spans] == ["ok"]


def test_normalize_spans_deterministic_ordering():
    payload = {
        "spans": [
            {"id": "b", "start": 5, "end": 8, "track": "t2"},
            {"id": "a", "start": 1, "end": 4, "track": "t1"},
            {"id": "c", "start": 2, "end": 3, "track": "t1"},
        ]
    }
    spans = normalize_spans(payload)
    assert [s["id"] for s in spans] == ["a", "c", "b"]


def test_normalize_spans_span_graph_time_range():
    payload = {
        "span_graph": [
            {"id": "sg1", "type": "shot", "timeRange": {"start": 0.5, "end": 2.0}, "summary": "intro"},
            {"id": "sg2", "type": "transition", "timeRange": {"start": 2.0, "end": 2.4}, "summary": "cut"},
        ]
    }
    spans = normalize_spans(payload)
    assert len(spans) == 2
    assert spans[0]["id"] == "sg1"
    assert spans[0]["track"] == "shot"
    assert spans[0]["start_ms"] == 500
    assert spans[0]["end_ms"] == 2000


def test_extract_json_object_with_wrapped_text():
    text = """Here is your result:
```json
{"span_graph":[{"id":"x","type":"shot","timeRange":{"start":0,"end":1}}]}
```
extra"""
    parsed = extract_json_object(text)
    assert parsed["span_graph"][0]["id"] == "x"
