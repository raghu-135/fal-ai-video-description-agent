from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from autohdr_pipeline.compiler import compile_render_plan
from autohdr_pipeline.generation import composition_timing_ms, extract_composed_video_url, ingredient_for_shot
from autohdr_pipeline.photo_inventory import analyze_photoshoot
from src.app.core.config import Settings
from src.app.main import app
from src.app.main_deps import get_autohdr_service
from src.app.services.autohdr_service import AutoHDRService
from src.app.ui.pages.autohdr import best_compile_shot_count, best_generation_shot_count, count_shot_spans, read_upload_event


def test_autohdr_service_create_run_and_guard_artifacts(tmp_path):
    service = AutoHDRService(Settings(fal_key="test", autohdr_runs_path=str(tmp_path)))

    manifest = service.create_run("https://example.com/reference.mp4", [("../kitchen.jpg", b"fake")])

    assert manifest["status"] == "created"
    assert manifest["photoCount"] == 1
    assert manifest["photos"][0]["filename"] == "kitchen.jpg"
    assert Path(manifest["photos"][0]["path"]).exists()

    try:
        service.artifact_path(manifest["id"], "../manifest.json")
    except ValueError:
        pass
    else:
        raise AssertionError("artifact_path should reject traversal")


def test_autohdr_service_create_run_persists_describe_output(tmp_path):
    service = AutoHDRService(Settings(fal_key="test", autohdr_runs_path=str(tmp_path)))
    describe_output = {"span_graph": [{"id": "shot_1", "type": "shot", "timeRange": {"start": 0, "end": 1}}]}

    manifest = service.create_run(
        "https://example.com/reference.mp4",
        [("photo.jpg", b"fake")],
        describe_output=describe_output,
    )

    describe_path = Path(manifest["artifacts"]["describeOutput"])
    assert json.loads(describe_path.read_text(encoding="utf-8")) == describe_output


def test_autohdr_api_create_run(tmp_path):
    service = AutoHDRService(Settings(fal_key="test", autohdr_runs_path=str(tmp_path)))
    app.dependency_overrides[get_autohdr_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/api/autohdr/runs",
            data={"reference_video_url": "https://example.com/reference.mp4"},
            files=[("photos", ("photo.jpg", b"fake", "image/jpeg"))],
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["photoCount"] == 1


def test_photo_inventory_generic_uploads_ignore_anmer_filename_profile(tmp_path):
    image_path = tmp_path / "IMG_2448.jpg"
    Image.new("RGB", (320, 200), (235, 235, 235)).save(image_path)

    inventory = analyze_photoshoot(tmp_path, use_filename_profile=False)

    assert inventory["assetCount"] == 1
    assert inventory["sourceAssets"][0]["spaceType"] != "kitchen"
    assert "filename profile disabled for generic uploads" in inventory["analysisNotes"]


def test_compile_render_plan_adds_top_level_ingredient_requests():
    style = {
        "id": "style",
        "substitutionPolicy": [],
        "shotSlots": [
            {
                "id": "shot_001",
                "referenceTimeRange": {"start": 0, "end": 4},
                "timeRange": {"start": 0, "end": 4, "duration": 4},
                "stylisticFunction": "feature_showcase",
                "contentTarget": {"spaceType": "living"},
                "compositionIntent": {"shotScale": "wide", "framing": "wide living room"},
                "cameraMotion": {"movement_type": "dolly_in", "speed": "slow", "direction": "windows"},
                "transitionOut": {"type": "cut"},
                "preferredVariantMode": "cinematic_light_variant",
            }
        ],
    }
    inventory = {
        "sourceFolder": "photos",
        "sourceAssets": [
            {
                "id": "asset_001",
                "path": "/tmp/living.jpg",
                "filename": "living.jpg",
                "spaceType": "living",
                "shotScale": "wide",
                "featureTags": ["windows"],
                "variantPotential": ["raw_passthrough", "cinematic_light_variant"],
                "motionSuitability": {"dolly_in": 0.9},
                "aestheticQuality": 0.8,
                "geometry": {"perspectiveRisk": "low"},
            }
        ],
    }

    plan = compile_render_plan(style, inventory)

    assert plan["ingredientRequests"][0]["shotSlotId"] == "shot_001"
    assert plan["ingredientRequests"][0]["status"] == "queued"
    assert ingredient_for_shot(plan, plan["timeline"][0])["status"] == "queued"


def test_read_upload_event_nicegui_file_shape():
    class File:
        name = "living.jpg"

        async def read(self):
            return b"image-bytes"

    class Event:
        file = File()

    assert asyncio.run(read_upload_event(Event())) == ("living.jpg", b"image-bytes")


def test_fal_compose_helpers_use_reference_timeline_and_video_url():
    record = {
        "shotSlotId": "ai_shot_001",
        "timeRange": {"start": 1.25, "duration": 2.5},
        "targetDuration": 2.5,
    }

    assert composition_timing_ms(record) == (1250, 2500)
    assert extract_composed_video_url({"video_url": "https://fal.example/final.mp4"}) == "https://fal.example/final.mp4"


def test_autohdr_final_generation_includes_reference_audio_by_default(tmp_path, monkeypatch):
    service = AutoHDRService(Settings(fal_key="test", autohdr_runs_path=str(tmp_path)))
    manifest = service.create_run("https://example.com/reference.mp4", [("photo.jpg", b"fake")])
    output_dir = service.output_dir(manifest["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    render_plan_path = output_dir / "render_plan.local.json"
    write_plan = {
        "id": "plan",
        "timeline": [
            {
                "shotSlotId": "shot_001",
                "timeRange": {"start": 0, "duration": 4},
            }
        ],
    }
    render_plan_path.write_text(json.dumps(write_plan), encoding="utf-8")
    manifest["artifacts"]["renderPlan"] = str(render_plan_path)
    service.save_manifest(manifest["id"], manifest)

    def fake_generate_fal_clips(*args, **kwargs):
        return {"shotCount": 1, "records": [{"shotSlotId": "shot_001", "clipUrl": "https://fal.example/clip.mp4"}]}

    def fake_compose_fal_video(generation_manifest, generation_dir, **kwargs):
        assert kwargs["reference_video_url"] == "https://example.com/reference.mp4"
        assert kwargs["include_reference_audio"] is True
        return {"finalVideoUrl": "https://fal.example/final.mp4", "thumbnailUrl": None}

    monkeypatch.setattr("src.app.services.autohdr_service.generate_fal_clips", fake_generate_fal_clips)
    monkeypatch.setattr("src.app.services.autohdr_service.compose_fal_video", fake_compose_fal_video)

    updated = service.generate_final_run(manifest["id"])

    assert updated["finalVideoUrl"] == "https://fal.example/final.mp4"


def test_autohdr_best_max_shot_counts(tmp_path):
    describe = {
        "span_graph": [
            {"type": "shot", "timeRange": {"start": 0, "end": 1}},
            {"type": "transition", "timeRange": {"start": 1, "end": 1.2}},
            {"type": "shot", "timeRange": {"start": 1.2, "end": 2}},
        ]
    }
    describe_path = tmp_path / "describe.json"
    describe_path.write_text(json.dumps(describe), encoding="utf-8")

    manifest = {"artifacts": {"describeOutput": str(describe_path)}, "timelineShotCount": 12}

    assert count_shot_spans(describe) == 2
    assert best_compile_shot_count(manifest) == 2
    assert best_generation_shot_count(manifest) == 12
