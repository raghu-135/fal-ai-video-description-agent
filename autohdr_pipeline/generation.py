"""Generate real clips from a multimodal render plan and assemble them."""

from __future__ import annotations

import json
import math
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .fal_tools import load_dotenv_if_needed
from .multimodal_compiler import upload_resized_image
from .utils import write_json


IMAGE_EDIT_ENDPOINT = "fal-ai/gemini-25-flash-image/edit"
VIDEO_ENDPOINT_FAST = "bytedance/seedance-2.0/fast/reference-to-video"
VIDEO_ENDPOINT_QUALITY = "bytedance/seedance-2.0/image-to-video"


def generate_and_assemble(
    render_plan: dict[str, Any],
    output_dir: Path,
    reference_audio: Path,
    *,
    r2_base_url: str = "https://r2-public.waqaas.workers.dev",
    video_model: str = VIDEO_ENDPOINT_FAST,
    image_edit_model: str = IMAGE_EDIT_ENDPOINT,
    resolution: str = "720p",
    max_shots: int | None = None,
    reuse_existing: bool = True,
    parallelism: int = 1,
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
                records_by_index[index] = future.result()
        generation_records = [records_by_index[index] for index, _ in indexed_timeline]
    else:
        generation_records = [
            generate_shot_record(
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
            for index, item in indexed_timeline
        ]

    assembled = output_dir / ("final_generated.mp4" if max_shots is None else f"final_generated_{len(timeline)}shots.mp4")
    assemble_clips(generation_records, assembled, reference_audio)
    result = {
        "schema": "generation_manifest.v1",
        "renderPlanId": render_plan["id"],
        "videoModel": video_model,
        "imageEditModel": image_edit_model,
        "parallelism": parallelism,
        "shotCount": len(timeline),
        "records": generation_records,
        "assembledVideo": str(assembled),
    }
    write_json(output_dir / "generation_manifest.json", result)
    return result


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
    ingredient = ingredient_for_shot(render_plan, shot_id)
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


def ingredient_for_shot(render_plan: dict[str, Any], shot_id: str) -> dict[str, Any] | None:
    for ingredient in render_plan.get("ingredientRequests", []):
        if ingredient.get("shotSlotId") == shot_id:
            return ingredient
    return None


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


def download_url(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.0.0"})
    with urllib.request.urlopen(request, timeout=240) as response:
        path.write_bytes(response.read())


def assemble_clips(records: list[dict[str, Any]], output_path: Path, reference_audio: Path) -> None:
    work_dir = output_path.parent / "generated" / "assembly"
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_list = work_dir / "concat.txt"
    segment_paths = []
    for index, record in enumerate(records, 1):
        segment = work_dir / f"segment_{index:03d}.mp4"
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            record["localClip"],
            "-t",
            f"{float(record['targetDuration']):.3f}",
            "-an",
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            str(segment),
        ]
        subprocess.run(command, check=True)
        segment_paths.append(segment)
    concat_list.write_text("".join(f"file '{path.resolve()}'\n" for path in segment_paths), encoding="utf-8")
    silent_video = work_dir / "silent_concat.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(silent_video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(silent_video),
            "-i",
            str(reference_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(output_path),
        ],
        check=True,
    )


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]
