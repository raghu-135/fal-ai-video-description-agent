"""Generate real clips from a multimodal render plan using Fal."""

from __future__ import annotations

import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .fal_tools import load_dotenv_if_needed
from .multimodal_compiler import upload_resized_image
from .utils import write_json


IMAGE_EDIT_ENDPOINT = "fal-ai/gemini-25-flash-image/edit"
VIDEO_ENDPOINT_FAST = "bytedance/seedance-2.0/fast/reference-to-video"
VIDEO_ENDPOINT_QUALITY = "bytedance/seedance-2.0/image-to-video"
COMPOSE_ENDPOINT = "fal-ai/ffmpeg-api/compose"


def generate_fal_clips(
    render_plan: dict[str, Any],
    output_dir: Path,
    *,
    r2_base_url: str = "https://r2-public.waqaas.workers.dev",
    video_model: str = VIDEO_ENDPOINT_FAST,
    image_edit_model: str = IMAGE_EDIT_ENDPOINT,
    resolution: str = "720p",
    max_shots: int | None = None,
    reuse_existing: bool = True,
    parallelism: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    load_dotenv_if_needed()
    import fal_client

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = output_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    job_prefix = f"autohdr-generation/{safe_id(render_plan['id'])}/{int(time.time())}"
    timeline = render_plan["timeline"][:max_shots] if max_shots else render_plan["timeline"]
    parallelism = len(timeline) if parallelism <= 0 else parallelism

    indexed_timeline = list(enumerate(timeline, 1))
    if parallelism > 1:
        print(f"[generate] parallelism={parallelism}", flush=True)
        records_by_index: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {
                executor.submit(
                    generate_shot_record,
                    fal_client,
                    render_plan,
                    item,
                    index,
                    len(timeline),
                    generated_dir,
                    job_prefix,
                    r2_base_url,
                    image_edit_model,
                    video_model,
                    resolution,
                    reuse_existing,
                ): index
                for index, item in indexed_timeline
            }
            for future in as_completed(futures):
                index = futures[future]
                record = future.result()
                records_by_index[index] = record
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "clip_generated",
                            "generatedShotCount": len(records_by_index),
                            "totalShotCount": len(timeline),
                            "currentShotId": record.get("shotSlotId"),
                            "localClip": record.get("localClip"),
                        }
                    )
        generation_records = [records_by_index[index] for index, _ in indexed_timeline]
    else:
        generation_records = []
        for index, item in indexed_timeline:
            record = generate_shot_record(
                fal_client,
                render_plan,
                item,
                index,
                len(timeline),
                generated_dir,
                job_prefix,
                r2_base_url,
                image_edit_model,
                video_model,
                resolution,
                reuse_existing,
            )
            generation_records.append(record)
            if progress_callback:
                progress_callback(
                    {
                        "stage": "clip_generated",
                        "generatedShotCount": len(generation_records),
                        "totalShotCount": len(timeline),
                        "currentShotId": record.get("shotSlotId"),
                        "localClip": record.get("localClip"),
                    }
                )

    result = {
        "schema": "generation_manifest.v1",
        "renderPlanId": render_plan["id"],
        "videoModel": video_model,
        "imageEditModel": image_edit_model,
        "parallelism": parallelism,
        "shotCount": len(timeline),
        "records": generation_records,
        "notes": [
            "Fal generated one clip per render-plan shot.",
            "No local preview or local final-video assembly was performed.",
        ],
    }
    write_json(output_dir / "generation_manifest.json", result)
    return result


def compose_fal_video(
    generation_manifest: dict[str, Any],
    output_dir: Path,
    *,
    endpoint: str = COMPOSE_ENDPOINT,
    reference_video_url: str | None = None,
    include_reference_audio: bool = False,
) -> dict[str, Any]:
    """Compose generated Fal clip URLs into one timeline using Fal's hosted FFmpeg API."""
    load_dotenv_if_needed()
    import fal_client

    records = generation_manifest.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Generation manifest has no clip records to compose.")

    keyframes = []
    for record in records:
        if not isinstance(record, dict):
            continue
        clip_url = record.get("clipUrl")
        if not isinstance(clip_url, str) or not clip_url:
            raise ValueError(f"Missing clipUrl for generated shot {record.get('shotSlotId')}")
        start_ms, duration_ms = composition_timing_ms(record)
        keyframes.append(
            {
                "timestamp": start_ms,
                "duration": duration_ms,
                "url": clip_url,
            }
        )
    if not keyframes:
        raise ValueError("No valid generated clip URLs were available for composition.")

    tracks: list[dict[str, Any]] = [{"id": "generated-video", "type": "video", "keyframes": keyframes}]
    if include_reference_audio and reference_video_url:
        total_duration_ms = max(frame["timestamp"] + frame["duration"] for frame in keyframes)
        tracks.append(
            {
                "id": "reference-audio",
                "type": "audio",
                "keyframes": [
                    {
                        "timestamp": 0,
                        "duration": total_duration_ms,
                        "url": reference_video_url,
                    }
                ],
            }
        )

    result = subscribe_job(
        fal_client,
        endpoint,
        arguments={"tracks": tracks},
        shot_id="final",
        stage="compose",
    )
    video_url = extract_composed_video_url(result)
    if not video_url:
        raise RuntimeError(f"No composed video URL returned: {result}")

    manifest = {
        "schema": "composition_manifest.v1",
        "renderPlanId": generation_manifest.get("renderPlanId"),
        "endpoint": endpoint,
        "referenceAudioIncluded": include_reference_audio and bool(reference_video_url),
        "shotCount": len(keyframes),
        "durationMs": max(frame["timestamp"] + frame["duration"] for frame in keyframes),
        "tracks": tracks,
        "result": result,
        "finalVideoUrl": video_url,
        "thumbnailUrl": result.get("thumbnail_url") if isinstance(result, dict) else None,
    }
    write_json(output_dir / "composition_manifest.json", manifest)

    generation_manifest["composition"] = manifest
    generation_manifest["finalVideoUrl"] = video_url
    generation_manifest["notes"] = [
        note
        for note in generation_manifest.get("notes", [])
        if note != "No local preview or local final-video assembly was performed."
    ]
    generation_manifest.setdefault("notes", []).append("Final video was composed by Fal ffmpeg-api/compose from generated clip URLs.")
    write_json(output_dir / "generation_manifest.json", generation_manifest)
    return manifest


def generate_shot_record(
    fal_client: Any,
    render_plan: dict[str, Any],
    item: dict[str, Any],
    index: int,
    total: int,
    generated_dir: Path,
    job_prefix: str,
    r2_base_url: str,
    image_edit_model: str,
    video_model: str,
    resolution: str,
    reuse_existing: bool,
) -> dict[str, Any]:
    shot_id = item["shotSlotId"]
    source_path = Path(item["selectedAsset"]["path"])
    source_key = f"{job_prefix}/source/{shot_id}.jpg"
    source_url = upload_resized_image(source_path, r2_base_url, source_key, max_edge=1600)
    ingredient = ingredient_for_shot(render_plan, item)
    ingredient_url = source_url
    edit_result = None
    if ingredient and ingredient["status"] == "queued":
        image_path = generated_dir / f"{shot_id}_ingredient.json"
        if reuse_existing and image_path.exists():
            edit_result = json.loads(image_path.read_text(encoding="utf-8"))
        else:
            edit_result = subscribe_job(
                fal_client,
                image_edit_model,
                arguments={
                    "prompt": ingredient["prompt"] or item["ingredientRequest"]["prompt"],
                    "image_urls": [source_url],
                    "num_images": 1,
                    "aspect_ratio": "16:9",
                    "output_format": "jpeg",
                    "safety_tolerance": "5",
                },
                shot_id=shot_id,
                stage="image-edit",
            )
            write_json(image_path, edit_result)
        ingredient_url = extract_image_url(edit_result) or source_url

    duration = generation_duration(item)
    video_path = generated_dir / f"{shot_id}_video.json"
    if reuse_existing and video_path.exists():
        video_result = json.loads(video_path.read_text(encoding="utf-8"))
    else:
        video_result = subscribe_job(
            fal_client,
            video_model,
            arguments=video_arguments(video_model, item, ingredient_url, resolution, duration),
            shot_id=shot_id,
            stage="video",
        )
        write_json(video_path, video_result)
    clip_url = extract_video_url(video_result)
    if not clip_url:
        raise RuntimeError(f"No video URL returned for {shot_id}: {video_result}")
    local_clip = generated_dir / f"{shot_id}.mp4"
    if not (reuse_existing and local_clip.exists()):
        download_url(clip_url, local_clip)

    record = {
        "shotSlotId": shot_id,
        "sourceImageUrl": source_url,
        "ingredientImageUrl": ingredient_url,
        "ingredientEditResult": edit_result,
        "videoResult": video_result,
        "clipUrl": clip_url,
        "localClip": str(local_clip),
        "timeRange": item["timeRange"],
        "targetDuration": item["timeRange"]["duration"],
        "generatedDurationRequest": duration,
        "videoModel": video_model,
        "imageEditModel": image_edit_model if edit_result else None,
    }
    print(f"[generate] {index}/{total} {shot_id} -> {local_clip}", flush=True)
    return record


def subscribe_job(
    fal_client: Any,
    endpoint: str,
    *,
    arguments: dict[str, Any],
    shot_id: str,
    stage: str,
) -> dict[str, Any]:
    def on_enqueue(request_id: str) -> None:
        print(f"[fal] {shot_id} {stage} request_id={request_id}", flush=True)

    def on_queue_update(update: Any) -> None:
        logs = getattr(update, "logs", None)
        if not logs:
            return
        for log in logs:
            message = log.get("message") if isinstance(log, dict) else str(log)
            if message:
                print(f"[fal] {shot_id} {stage}: {message}", flush=True)

    last_error = None
    for attempt in range(1, 4):
        try:
            return fal_client.subscribe(
                endpoint,
                arguments=arguments,
                with_logs=True,
                on_enqueue=on_enqueue,
                on_queue_update=on_queue_update,
                client_timeout=900,
            )
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                print(f"[fal] {shot_id} {stage} retry {attempt}/2 after error: {exc}", flush=True)
                time.sleep(3 * attempt)
    raise last_error


def ingredient_for_shot(render_plan: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    shot_id = item["shotSlotId"]
    for ingredient in render_plan.get("ingredientRequests", []):
        if ingredient.get("shotSlotId") == shot_id:
            return ingredient
    request = item.get("ingredientRequest")
    if not isinstance(request, dict):
        return None
    mode = request.get("mode") or item.get("ingredientVariantMode")
    return {
        "id": item.get("ingredientVariantId") or f"{shot_id}__{item['selectedAsset']['id']}__{mode}",
        "shotSlotId": shot_id,
        "sourceAsset": item.get("selectedAsset"),
        "mode": mode,
        "status": "not_required" if mode == "raw_passthrough" else "queued",
        "prompt": request.get("prompt"),
        "preservationConstraints": request.get("preservationConstraints", []),
        "riskLevel": request.get("riskLevel", "low"),
        "requiresHumanReview": False,
    }


def generation_duration(item: dict[str, Any]) -> int:
    duration = float(item["timeRange"]["duration"])
    return max(4, min(15, math.ceil(duration)))


def video_arguments(
    video_model: str,
    item: dict[str, Any],
    ingredient_url: str,
    resolution: str,
    duration: int,
) -> dict[str, Any]:
    arguments = {
        "prompt": item["videoGeneration"].get("modelSpecificPrompt") or item["videoGeneration"]["prompt"],
        "resolution": resolution,
        "duration": str(duration),
        "aspect_ratio": "16:9",
        "generate_audio": False,
    }
    if video_model.endswith("/reference-to-video"):
        arguments["image_urls"] = [ingredient_url]
    else:
        arguments["image_url"] = ingredient_url
    return arguments


def extract_image_url(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    for key in ("images", "image"):
        value = result.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                return first["url"]
        if isinstance(value, dict) and isinstance(value.get("url"), str):
            return value["url"]
    return None


def extract_video_url(result: dict[str, Any]) -> str | None:
    video = result.get("video")
    if isinstance(video, dict) and isinstance(video.get("url"), str):
        return video["url"]
    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"]
    return None


def extract_composed_video_url(result: dict[str, Any]) -> str | None:
    url = result.get("video_url")
    if isinstance(url, str):
        return url
    video = result.get("video")
    if isinstance(video, dict) and isinstance(video.get("url"), str):
        return video["url"]
    return extract_video_url(result)


def composition_timing_ms(record: dict[str, Any]) -> tuple[int, int]:
    start_seconds = 0.0
    time_range = record.get("timeRange")
    if isinstance(time_range, dict) and isinstance(time_range.get("start"), (int, float)):
        start_seconds = float(time_range["start"])
    duration = record.get("targetDuration")
    if not isinstance(duration, (int, float)):
        duration = record.get("generatedDurationRequest")
    if not isinstance(duration, (int, float)):
        raise ValueError(f"Missing target duration for generated shot {record.get('shotSlotId')}")
    return round(start_seconds * 1000), max(1, round(float(duration) * 1000))


def download_url(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.0.0"})
    with urllib.request.urlopen(request, timeout=240) as response:
        path.write_bytes(response.read())


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]
