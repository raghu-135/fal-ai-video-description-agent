from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = Path(os.environ.get("AUTOHDR_DEMO_RUNS_DIR", str(ROOT / "demo_runs")))
R2_BASE_URL = os.environ.get("AUTOHDR_R2_BASE_URL", "https://r2-public.waqaas.workers.dev").rstrip("/")
R2_PREFIX = os.environ.get("AUTOHDR_DEMO_R2_PREFIX", "autohdr-demo").strip("/")
FINAL_OUTPUT_PREFIX = os.environ.get("AUTOHDR_FINAL_VIDEO_PREFIX", "autohdr-output").strip("/")
DEMO_VIDEO_UNDERSTANDING_MODEL = os.environ.get("AUTOHDR_DEMO_VIDEO_UNDERSTANDING_MODEL", "google/gemini-3.1-pro-preview")
DEMO_MULTIMODAL_MODEL = os.environ.get("AUTOHDR_DEMO_MULTIMODAL_MODEL", "google/gemini-3.1-pro-preview")
DEMO_MULTIMODAL_MAX_CANDIDATES = os.environ.get("AUTOHDR_DEMO_MULTIMODAL_MAX_CANDIDATES", "0")
DEMO_GENERATION_VIDEO_MODEL = os.environ.get("AUTOHDR_DEMO_GENERATION_VIDEO_MODEL", "bytedance/seedance-2.0/image-to-video")
DEMO_GENERATION_RESOLUTION = os.environ.get("AUTOHDR_DEMO_GENERATION_RESOLUTION", "1080p")
DEMO_PREVIEW_WIDTH = os.environ.get("AUTOHDR_DEMO_PREVIEW_WIDTH", "1280")
DEMO_PREVIEW_HEIGHT = os.environ.get("AUTOHDR_DEMO_PREVIEW_HEIGHT", "720")
DEMO_PREVIEW_FPS = os.environ.get("AUTOHDR_DEMO_PREVIEW_FPS", "24")
REFERENCE_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = REFERENCE_EXTENSIONS
R2_LIST_LIMIT = int(os.environ.get("AUTOHDR_R2_LIST_LIMIT", "1000"))
R2_LIST_MAX_PAGES = int(os.environ.get("AUTOHDR_R2_LIST_MAX_PAGES", "8"))
RUN_THREADS: dict[str, threading.Thread] = {}


app = FastAPI(title="AutoHDR Hackathon Demo")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/runs")
async def create_run(
    reference_video: UploadFile | None = File(None),
    reference_url: str | None = Form(None),
    photos: list[UploadFile] = File(...),
) -> dict[str, Any]:
    if not photos:
        raise HTTPException(status_code=400, detail="Upload at least one photoshoot image.")

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    run_dir = run_dir_for(run_id)
    inputs_dir = run_dir / "inputs"
    photos_dir = inputs_dir / "photos"
    output_dir = run_dir / "outputs"
    photos_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    bucket_reference_url = normalize_bucket_video_url(reference_url)
    if bucket_reference_url:
        reference_suffix = suffix_for_url(bucket_reference_url)
        reference_path = inputs_dir / f"reference{reference_suffix}"
        download_to_path(bucket_reference_url, reference_path)
        reference_source = "bucket"
    else:
        if reference_video is None or not reference_video.filename:
            raise HTTPException(status_code=400, detail="Choose a bucket reference or upload a reference video.")
        reference_name = safe_name(reference_video.filename or "reference.mp4", "reference.mp4")
        reference_suffix = Path(reference_name).suffix.lower()
        if reference_suffix not in REFERENCE_EXTENSIONS:
            reference_suffix = ".mp4"
        reference_path = inputs_dir / f"reference{reference_suffix}"
        await save_upload(reference_video, reference_path)
        reference_source = "upload"

    photo_records = []
    for index, photo in enumerate(photos, 1):
        photo_name = safe_name(photo.filename or f"photo_{index:03d}.jpg", f"photo_{index:03d}.jpg")
        if Path(photo_name).suffix.lower() not in PHOTO_EXTENSIONS:
            continue
        photo_path = photos_dir / f"{index:03d}_{Path(photo_name).name}"
        await save_upload(photo, photo_path)
        photo_records.append({"name": photo_name, "path": str(photo_path), "sizeBytes": photo_path.stat().st_size})

    if not photo_records:
        raise HTTPException(status_code=400, detail="No supported photos were uploaded.")

    manifest = {
        "schema": "autohdr_demo_run.v1",
        "id": run_id,
        "status": "uploading_reference",
        "stage": "upload_reference",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "referenceVideoPath": str(reference_path),
        "referenceVideoUrl": bucket_reference_url,
        "referenceVideoSource": reference_source,
        "photosDir": str(photos_dir),
        "photoCount": len(photo_records),
        "photos": photo_records,
        "outputDir": str(output_dir),
        "progress": {"stage": "upload_reference", "current": 0, "total": 1, "label": "Preparing reference"},
        "artifacts": {},
        "error": None,
    }
    save_manifest(run_id, manifest)
    append_log(run_id, f"Created run with {len(photo_records)} photos")

    if bucket_reference_url:
        append_log(run_id, f"Using bucket reference: {bucket_reference_url}")
    else:
        content_type = reference_video.content_type or mimetypes.guess_type(reference_path.name)[0] or "video/mp4"
        r2_key = f"{R2_PREFIX}/{run_id}/reference{reference_suffix}"
        uploaded_reference_url = upload_to_r2(reference_path, r2_key, content_type)
        manifest["referenceVideoUrl"] = uploaded_reference_url
        append_log(run_id, f"Reference uploaded: {uploaded_reference_url}")
    manifest["status"] = "ready"
    manifest["stage"] = "ready"
    manifest["progress"] = {"stage": "ready", "current": 1, "total": 1, "label": "Ready to run"}
    save_manifest(run_id, manifest)
    return public_status(manifest)


@app.get("/api/bucket/videos")
def list_bucket_videos() -> dict[str, Any]:
    try:
        objects = list_bucket_video_objects()
    except Exception as exc:
        return {
            "baseUrl": R2_BASE_URL,
            "references": [],
            "finals": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    references = sorted(
        [item for item in objects.values() if is_reference_video_key(item["key"])],
        key=lambda item: item.get("uploaded") or "",
        reverse=True,
    )
    finals = sorted(
        [item for item in objects.values() if is_final_video_key(item["key"])],
        key=lambda item: item.get("uploaded") or "",
        reverse=True,
    )
    return {
        "baseUrl": R2_BASE_URL,
        "references": references,
        "finals": finals,
        "videoCount": len(objects),
    }


@app.post("/api/runs/{run_id}/start")
def start_run(run_id: str) -> dict[str, Any]:
    manifest = load_manifest(run_id)
    if manifest["status"] == "running":
        return public_status(manifest)
    if run_id in RUN_THREADS and RUN_THREADS[run_id].is_alive():
        return public_status(manifest)

    thread = threading.Thread(target=run_pipeline, args=(run_id,), daemon=True)
    RUN_THREADS[run_id] = thread
    thread.start()
    manifest["status"] = "running"
    manifest["stage"] = "queued"
    manifest["progress"] = {"stage": "queued", "current": 0, "total": 1, "label": "Queued"}
    manifest["updatedAt"] = now_iso()
    save_manifest(run_id, manifest)
    return public_status(manifest)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return public_status(load_manifest(run_id))


@app.get("/api/runs/{run_id}/files/{relative_path:path}")
def get_file(run_id: str, relative_path: str) -> FileResponse:
    base = run_dir_for(run_id).resolve()
    path = (base / relative_path).resolve()
    if base != path and base not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


def run_pipeline(run_id: str) -> None:
    manifest = load_manifest(run_id)
    output_dir = Path(manifest["outputDir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    set_progress(run_id, "span_graph", 0, 1, "Extracting span graph")

    command = build_pipeline_command(manifest, output_dir)
    append_log(run_id, "Starting pipeline")
    append_log(
        run_id,
        "Quality profile: "
        f"video_understanding={DEMO_VIDEO_UNDERSTANDING_MODEL}; "
        f"multimodal={DEMO_MULTIMODAL_MODEL}; "
        f"multimodal_candidates={DEMO_MULTIMODAL_MAX_CANDIDATES}; "
        f"generation_model={DEMO_GENERATION_VIDEO_MODEL}; "
        f"generation_resolution={DEMO_GENERATION_RESOLUTION}; "
        "parallelism=0",
    )
    append_log(run_id, " ".join(command))
    manifest["status"] = "running"
    manifest["stage"] = "running"
    manifest["updatedAt"] = now_iso()
    save_manifest(run_id, manifest)

    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if not line:
                continue
            append_log(run_id, line)
            update_progress_from_line(run_id, line)
        return_code = process.wait()
    except Exception as exc:
        mark_failed(run_id, exc)
        return

    manifest = load_manifest(run_id)
    final_path = Path(manifest["outputDir"]) / "final_generated.mp4"
    if return_code == 0 and final_path.exists():
        try:
            final_key = f"{FINAL_OUTPUT_PREFIX}/{run_id}-final.mp4"
            manifest["finalVideoBucketUrl"] = upload_to_r2(final_path, final_key, "video/mp4", timeout=600)
            append_log(run_id, f"Final uploaded: {manifest['finalVideoBucketUrl']}")
        except Exception as exc:
            append_log(run_id, f"WARNING: final R2 upload failed: {type(exc).__name__}: {exc}")
        manifest["status"] = "completed"
        manifest["stage"] = "completed"
        manifest["progress"] = {"stage": "completed", "current": 1, "total": 1, "label": "Final video ready"}
        manifest["error"] = None
    else:
        manifest["status"] = "failed"
        manifest["stage"] = "failed"
        manifest["error"] = {"message": f"Pipeline exited with code {return_code}", "type": "PipelineError"}
    manifest["updatedAt"] = now_iso()
    save_manifest(run_id, manifest)
    append_log(run_id, f"Pipeline exited with code {return_code}")


def build_pipeline_command(manifest: dict[str, Any], output_dir: Path) -> list[str]:
    command = [
        sys.executable,
        "-B",
        "-m",
        "autohdr_pipeline.pipeline",
        "--reference",
        manifest["referenceVideoPath"],
        "--reference-url",
        manifest["referenceVideoUrl"],
        "--photoshoot",
        manifest["photosDir"],
        "--output-dir",
        str(output_dir),
        "--ai-style",
        "--shot-style-fragments",
        "--video-understanding-endpoint",
        "openrouter/router/video",
        "--video-understanding-model",
        DEMO_VIDEO_UNDERSTANDING_MODEL,
        "--video-understanding-max-tokens",
        "96000",
        "--video-understanding-temperature",
        "0.05",
        "--shot-style-fragments-max-tokens",
        "16000",
        "--shot-style-fragments-parallelism",
        "0",
        "--multimodal-compile",
        "--multimodal-model",
        DEMO_MULTIMODAL_MODEL,
        "--multimodal-max-candidates",
        DEMO_MULTIMODAL_MAX_CANDIDATES,
        "--multimodal-parallelism",
        "0",
        "--r2-base-url",
        R2_BASE_URL,
        "--preview",
        "--preview-output",
        str(output_dir / "preview.mp4"),
        "--preview-width",
        DEMO_PREVIEW_WIDTH,
        "--preview-height",
        DEMO_PREVIEW_HEIGHT,
        "--preview-fps",
        DEMO_PREVIEW_FPS,
        "--generate",
        "--generation-resolution",
        DEMO_GENERATION_RESOLUTION,
        "--generation-video-model",
        DEMO_GENERATION_VIDEO_MODEL,
        "--generation-parallelism",
        "0",
    ]
    return command


def update_progress_from_line(run_id: str, line: str) -> None:
    if "[segment-style] parallelism=" in line:
        total = int(line.rsplit("=", 1)[-1])
        set_progress(run_id, "span_enrichment", 0, total, "Enriching shot spans")
        return
    if match := re.search(r"\[segment-style\]\s+(\d+)/(\d+)", line):
        set_progress(run_id, "span_enrichment", int(match.group(1)), int(match.group(2)), "Enriching shot spans")
        return
    if "[multimodal] parallelism=" in line:
        total = int(line.rsplit("=", 1)[-1])
        set_progress(run_id, "multimodal", 0, total, "Choosing photos with multimodal compiler")
        return
    if match := re.search(r"\[multimodal\]\s+(?:model result|apply)\s+(\d+)/(\d+)", line):
        set_progress(run_id, "multimodal", int(match.group(1)), int(match.group(2)), "Choosing photos with multimodal compiler")
        return
    if "[generate] parallelism=" in line:
        total = int(line.rsplit("=", 1)[-1])
        set_progress(run_id, "generation", 0, total, "Generating video shots")
        return
    if match := re.search(r"\[generate\]\s+(\d+)/(\d+)", line):
        set_progress(run_id, "generation", int(match.group(1)), int(match.group(2)), "Generating video shots")
        return
    if "Wrote " in line and "preview.mp4" in line:
        set_progress(run_id, "preview", 1, 1, "Preview ready")
        return
    if "Wrote " in line and "final_generated.mp4" in line:
        set_progress(run_id, "assembly", 1, 1, "Assembling final video")


def public_status(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = {**manifest}
    run_id = manifest["id"]
    output_dir = Path(manifest["outputDir"])
    artifacts = {
        "spanGraphUrl": artifact_url(run_id, output_dir / "fal_span_graph.parsed.json"),
        "shotStyleFragmentsUrl": artifact_url(run_id, output_dir / "shot_style_fragments.json"),
        "renderPlanUrl": artifact_url(run_id, output_dir / "render_plan.ai.multimodal.json"),
        "multimodalDecisionsUrl": artifact_url(run_id, output_dir / "multimodal_compiler_decisions.json"),
        "previewVideoUrl": artifact_url(run_id, output_dir / "preview.mp4"),
        "finalVideoUrl": artifact_url(run_id, output_dir / "final_generated.mp4"),
        "finalVideoBucketUrl": manifest.get("finalVideoBucketUrl"),
        "logUrl": artifact_url(run_id, run_dir_for(run_id) / "pipeline.log"),
    }
    manifest["artifacts"] = artifacts
    manifest["counts"] = artifact_counts(output_dir)
    manifest["logTail"] = log_tail(run_id)
    manifest.pop("referenceVideoPath", None)
    manifest.pop("photosDir", None)
    manifest.pop("outputDir", None)
    manifest.pop("photos", None)
    return manifest


def artifact_counts(output_dir: Path) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    fragments = read_json(output_dir / "shot_style_fragments.json")
    if fragments:
        counts["shotStyleFragments"] = fragments.get("extractedCount") or len(fragments.get("records", []))
    decisions = read_json(output_dir / "multimodal_compiler_decisions.json")
    if decisions:
        counts["multimodalDecisions"] = len(decisions.get("decisions", []))
    plan = read_json(output_dir / "render_plan.ai.multimodal.json") or read_json(output_dir / "render_plan.ai.json")
    if plan:
        counts["timelineShots"] = len(plan.get("timeline", []))
        counts["durationTarget"] = plan.get("durationTarget")
    generated_dir = output_dir / "generated"
    if generated_dir.exists():
        counts["generatedClips"] = len(list(generated_dir.glob("*.mp4")))
    return counts


def artifact_url(run_id: str, path: Path) -> str | None:
    if not path.exists():
        return None
    relative = path.resolve().relative_to(run_dir_for(run_id).resolve())
    return f"/api/runs/{run_id}/files/{relative.as_posix()}"


def set_progress(run_id: str, stage: str, current: int, total: int, label: str) -> None:
    manifest = load_manifest(run_id)
    manifest["status"] = "running"
    manifest["stage"] = stage
    manifest["progress"] = {"stage": stage, "current": current, "total": total, "label": label}
    manifest["updatedAt"] = now_iso()
    save_manifest(run_id, manifest)


def mark_failed(run_id: str, exc: Exception) -> None:
    manifest = load_manifest(run_id)
    manifest["status"] = "failed"
    manifest["stage"] = "failed"
    manifest["error"] = {"message": str(exc), "type": type(exc).__name__}
    manifest["updatedAt"] = now_iso()
    save_manifest(run_id, manifest)
    append_log(run_id, f"ERROR: {type(exc).__name__}: {exc}")


async def save_upload(upload: UploadFile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            handle.write(chunk)


def upload_to_r2(path: Path, key: str, content_type: str, *, timeout: int = 240) -> str:
    url = f"{R2_BASE_URL}/{key}"
    request = urllib.request.Request(
        url,
        data=path.read_bytes(),
        method="PUT",
        headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"R2 upload failed with HTTP {response.status}")
    return url


def download_to_path(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "AutoHDR-Demo/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, path.open("wb") as handle:
        if response.status >= 300:
            raise HTTPException(status_code=400, detail=f"Bucket reference download failed with HTTP {response.status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def list_bucket_video_objects() -> dict[str, dict[str, Any]]:
    prefixes = ["", R2_PREFIX, FINAL_OUTPUT_PREFIX, "references", "reference-videos", "autohdr-output"]
    items: dict[str, dict[str, Any]] = {}
    for prefix in dict.fromkeys(prefix.strip("/") for prefix in prefixes):
        for object_record in list_r2_objects(prefix):
            key = str(object_record.get("key") or "")
            if not is_video_key(key):
                continue
            items[key] = normalize_bucket_object(object_record)
    return items


def list_r2_objects(prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    cursor = None
    for _ in range(max(R2_LIST_MAX_PAGES, 1)):
        params = {"list": "1", "prefix": prefix, "limit": str(R2_LIST_LIMIT)}
        if cursor:
            params["cursor"] = cursor
        url = f"{R2_BASE_URL}/?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "AutoHDR-Demo/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("R2 Worker list endpoint is not deployed yet") from exc
        objects.extend(payload.get("objects", []))
        cursor = payload.get("cursor")
        if not payload.get("truncated") or not cursor:
            break
    return objects


def normalize_bucket_object(object_record: dict[str, Any]) -> dict[str, Any]:
    key = str(object_record.get("key") or "")
    return {
        "key": key,
        "url": f"{R2_BASE_URL}/{urllib.parse.quote(key, safe='/._-~')}",
        "label": bucket_label(key),
        "sizeBytes": object_record.get("size"),
        "uploaded": object_record.get("uploaded"),
    }


def normalize_bucket_video_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlparse(value.strip())
    base = urllib.parse.urlparse(R2_BASE_URL)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise HTTPException(status_code=400, detail="Bucket reference URL must come from the configured R2 Worker.")
    clean_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    if not is_video_key(urllib.parse.unquote(parsed.path)):
        raise HTTPException(status_code=400, detail="Selected bucket reference must be a supported video file.")
    return clean_url


def suffix_for_url(url: str) -> str:
    suffix = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).suffix.lower()
    return suffix if suffix in REFERENCE_EXTENSIONS else ".mp4"


def is_video_key(key: str) -> bool:
    return Path(urllib.parse.unquote(key)).suffix.lower() in VIDEO_EXTENSIONS


def is_reference_video_key(key: str) -> bool:
    lower = key.lower()
    if not is_video_key(key) or is_final_video_key(key):
        return False
    return (
        "/" not in lower
        or lower.startswith(f"{R2_PREFIX.lower()}/")
        or lower.startswith("references/")
        or lower.startswith("reference-videos/")
        or "/reference" in lower
    )


def is_final_video_key(key: str) -> bool:
    lower = key.lower()
    if not is_video_key(key):
        return False
    return (
        lower.startswith(f"{FINAL_OUTPUT_PREFIX.lower()}/")
        or lower.startswith("autohdr-output/")
        or "final_generated" in lower
        or lower.endswith("-final.mp4")
    )


def bucket_label(key: str) -> str:
    parts = [part for part in key.split("/") if part]
    if len(parts) >= 2 and parts[-1].startswith("reference"):
        return f"{parts[-2]} / {parts[-1]}"
    return parts[-1] if parts else key


def append_log(run_id: str, line: str) -> None:
    path = run_dir_for(run_id) / "pipeline.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().strftime('%H:%M:%S')} {line}\n")


def log_tail(run_id: str, max_lines: int = 140) -> list[str]:
    path = run_dir_for(run_id) / "pipeline.log"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]


def run_dir_for(run_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "", run_id)
    if safe_id != run_id:
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return RUNS_DIR / run_id


def manifest_path(run_id: str) -> Path:
    return run_dir_for(run_id) / "manifest.json"


def load_manifest(run_id: str) -> dict[str, Any]:
    path = manifest_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(run_id: str, manifest: dict[str, Any]) -> None:
    path = manifest_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def safe_name(value: str, fallback: str) -> str:
    name = Path(value or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoHDR Demo</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --ink: #151922;
      --muted: #657084;
      --line: #d9dee8;
      --blue: #246bfe;
      --green: #16875a;
      --red: #c53939;
      --amber: #9a6a10;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    main { display: grid; grid-template-columns: minmax(320px, 420px) 1fr; min-height: 100vh; }
    aside, section { padding: 20px; }
    aside { border-right: 1px solid var(--line); background: var(--panel); }
    h1 { margin: 0 0 16px; font-size: 22px; line-height: 1.15; }
    h2 { margin: 0 0 12px; font-size: 15px; }
    label { display: block; margin: 12px 0 6px; color: var(--muted); font-size: 13px; font-weight: 600; }
    input[type=file], select { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    button {
      width: 100%;
      height: 40px;
      border: 0;
      border-radius: 8px;
      background: var(--blue);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: #303846; }
    button.compact { width: auto; height: 34px; padding: 0 12px; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    .stack { display: grid; gap: 12px; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }
    .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    .grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: 14px; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 10px; }
    .stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .stat span { display: block; color: var(--muted); font-size: 12px; }
    .stat strong { display: block; margin-top: 4px; font-size: 18px; }
    .status { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--amber); }
    .dot.completed { background: var(--green); }
    .dot.failed { background: var(--red); }
    .bar { position: relative; height: 10px; overflow: hidden; border-radius: 999px; background: #e9edf5; }
    .bar > div { height: 100%; width: 0%; background: var(--blue); transition: width .25s ease; }
    .timeline { position: relative; display: grid; gap: 8px; min-height: 300px; }
    .track { display: grid; grid-template-columns: 110px 1fr; gap: 10px; align-items: center; min-height: 28px; }
    .track-name { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .track-line { position: relative; height: 28px; border-radius: 6px; background: #f1f4f8; overflow: hidden; }
    .span {
      position: absolute;
      top: 4px;
      height: 20px;
      min-width: 2px;
      border-radius: 5px;
      background: #246bfe;
      color: white;
      font-size: 10px;
      line-height: 20px;
      padding: 0 5px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    video { width: 100%; max-height: 520px; border-radius: 8px; background: #111; }
    pre {
      height: 300px;
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      color: #dbe7ff;
      background: #111722;
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }
    .links { display: flex; flex-wrap: wrap; gap: 8px; }
    .links a {
      color: var(--blue);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      text-decoration: none;
      background: #fbfcfe;
      font-size: 13px;
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .grid, .stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <aside>
      <h1>AutoHDR Demo</h1>
      <form id="uploadForm" class="stack">
        <div>
          <div class="row">
            <label for="referenceSelect">Bucket reference</label>
            <button id="bucketRefreshButton" class="compact secondary" type="button">Refresh</button>
          </div>
          <select id="referenceSelect" name="reference_url">
            <option value="">Upload new reference</option>
          </select>
          <p id="bucketStatus" style="color:var(--muted);font-size:12px;margin:6px 0 0">Bucket list not loaded.</p>
        </div>
        <div>
          <label for="reference">Upload reference</label>
          <input id="reference" name="reference_video" type="file" accept="video/*">
        </div>
        <div>
          <label for="photos">Photoshoot images</label>
          <input id="photos" name="photos" type="file" accept="image/*" multiple webkitdirectory directory required>
        </div>
        <div class="actions">
          <button id="createButton" type="submit">Upload</button>
          <button id="startButton" class="secondary" type="button" disabled>Run</button>
        </div>
      </form>
      <div class="panel" style="margin-top:16px">
        <div class="status"><span id="dot" class="dot"></span><span id="statusText">No run loaded</span></div>
        <p id="runId" style="color:var(--muted);font-size:13px;margin:8px 0 0"></p>
      </div>
      <div class="panel" style="margin-top:16px">
        <h2>Progress</h2>
        <div class="bar"><div id="progressFill"></div></div>
        <p id="progressText" style="margin:8px 0 0;color:var(--muted);font-size:13px">Waiting</p>
      </div>
      <div class="panel" style="margin-top:16px">
        <h2>Artifacts</h2>
        <div id="artifactLinks" class="links"></div>
      </div>
    </aside>
    <section class="stack">
      <div class="stats">
        <div class="stat"><span>Photos</span><strong id="photoCount">0</strong></div>
        <div class="stat"><span>Shots</span><strong id="shotCount">0</strong></div>
        <div class="stat"><span>Enriched</span><strong id="fragmentCount">0</strong></div>
        <div class="stat"><span>Generated</span><strong id="clipCount">0</strong></div>
      </div>
      <div class="grid">
        <div class="panel">
          <h2>Span Map</h2>
          <div id="spanMap" class="timeline"></div>
        </div>
        <div class="panel">
          <h2>Final Video</h2>
          <div class="row" style="margin-bottom:10px">
            <select id="finalSelect">
              <option value="">Bucket final videos</option>
            </select>
            <button id="previewFinalButton" class="compact secondary" type="button">Preview</button>
          </div>
          <div id="finalVideo">No final video yet.</div>
        </div>
      </div>
      <div class="panel">
        <h2>Pipeline Log</h2>
        <pre id="log"></pre>
      </div>
    </section>
  </main>
  <script>
    let currentRunId = null;
    let pollTimer = null;
    let spanGraphLoadedFor = null;

    const uploadForm = document.getElementById('uploadForm');
    const referenceInput = document.getElementById('reference');
    const photosInput = document.getElementById('photos');
    const referenceSelect = document.getElementById('referenceSelect');
    const finalSelect = document.getElementById('finalSelect');
    const createButton = document.getElementById('createButton');
    const startButton = document.getElementById('startButton');
    const bucketRefreshButton = document.getElementById('bucketRefreshButton');
    const previewFinalButton = document.getElementById('previewFinalButton');

    const savedRunId = localStorage.getItem('autohdrCurrentRunId');
    if (savedRunId) {
      currentRunId = savedRunId;
      beginPolling();
    }
    loadBucketVideos();

    bucketRefreshButton.addEventListener('click', loadBucketVideos);
    previewFinalButton.addEventListener('click', () => {
      if (!finalSelect.value) return;
      renderVideo(finalSelect.value);
    });

    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      createButton.disabled = true;
      setStatus({status: 'uploading', progress: {label: 'Uploading inputs', current: 0, total: 1}});
      try {
        const formData = buildRunFormData();
        const response = await fetch('/api/runs', {method: 'POST', body: formData});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Upload failed');
        currentRunId = payload.id;
        localStorage.setItem('autohdrCurrentRunId', currentRunId);
        spanGraphLoadedFor = null;
        startButton.disabled = false;
        renderStatus(payload);
        beginPolling();
      } catch (error) {
        alert(error.message);
      } finally {
        createButton.disabled = false;
      }
    });

    function buildRunFormData() {
      const formData = new FormData();
      if (referenceSelect.value) {
        formData.append('reference_url', referenceSelect.value);
      } else if (referenceInput.files.length) {
        formData.append('reference_video', referenceInput.files[0], referenceInput.files[0].name);
      } else {
        throw new Error('Choose a bucket reference or upload a reference video.');
      }

      for (const file of photosInput.files) {
        formData.append('photos', file, file.webkitRelativePath || file.name);
      }
      if (!photosInput.files.length) {
        throw new Error('Upload at least one photoshoot image.');
      }
      return formData;
    }

    async function loadBucketVideos() {
      bucketRefreshButton.disabled = true;
      document.getElementById('bucketStatus').textContent = 'Loading bucket videos...';
      try {
        const response = await fetch('/api/bucket/videos');
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Bucket query failed');
        renderBucketVideos(payload);
      } catch (error) {
        document.getElementById('bucketStatus').textContent = error.message;
      } finally {
        bucketRefreshButton.disabled = false;
      }
    }

    function renderBucketVideos(payload) {
      const selectedReference = referenceSelect.value;
      const selectedFinal = finalSelect.value;
      const references = payload.references || [];
      const finals = payload.finals || [];
      referenceSelect.innerHTML = '<option value="">Upload new reference</option>' +
        references.map(item => bucketOption(item)).join('');
      finalSelect.innerHTML = '<option value="">Bucket final videos</option>' +
        finals.map(item => bucketOption(item)).join('');
      referenceSelect.value = references.some(item => item.url === selectedReference) ? selectedReference : '';
      finalSelect.value = finals.some(item => item.url === selectedFinal) ? selectedFinal : '';
      const status = payload.error
        ? `Bucket list unavailable: ${payload.error}`
        : `${references.length} references, ${finals.length} finals`;
      document.getElementById('bucketStatus').textContent = status;
    }

    function bucketOption(item) {
      const size = item.sizeBytes ? ` · ${formatBytes(item.sizeBytes)}` : '';
      return `<option value="${escapeHtml(item.url)}">${escapeHtml(item.label || item.key)}${size}</option>`;
    }

    startButton.addEventListener('click', async () => {
      if (!currentRunId) return;
      startButton.disabled = true;
      const response = await fetch(`/api/runs/${currentRunId}/start`, {method: 'POST'});
      const payload = await response.json();
      if (!response.ok) {
        alert(payload.detail || 'Run failed to start');
        startButton.disabled = false;
        return;
      }
      renderStatus(payload);
      beginPolling();
    });

    function beginPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshRun, 2500);
      refreshRun();
    }

    async function refreshRun() {
      if (!currentRunId) return;
      const response = await fetch(`/api/runs/${currentRunId}`);
      if (!response.ok) return;
      const payload = await response.json();
      renderStatus(payload);
      if (payload.status === 'completed' || payload.status === 'failed') {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function renderStatus(run) {
      setStatus(run);
      document.getElementById('runId').textContent = run.id ? `Run ${run.id}` : '';
      document.getElementById('photoCount').textContent = run.photoCount || 0;
      document.getElementById('shotCount').textContent = run.counts?.timelineShots || 0;
      document.getElementById('fragmentCount').textContent = run.counts?.shotStyleFragments || 0;
      document.getElementById('clipCount').textContent = run.counts?.generatedClips || 0;
      document.getElementById('log').textContent = (run.logTail || []).join('\n');
      renderArtifacts(run.artifacts || {});
      renderFinalVideo(run.artifacts || {});
      if (run.artifacts?.spanGraphUrl && spanGraphLoadedFor !== run.id) {
        spanGraphLoadedFor = run.id;
        loadSpanGraph(run.artifacts.spanGraphUrl);
      }
      startButton.disabled = !run.id || run.status === 'running' || run.status === 'completed';
    }

    function setStatus(run) {
      const dot = document.getElementById('dot');
      const status = run.status || 'idle';
      dot.className = `dot ${status}`;
      document.getElementById('statusText').textContent = status;
      const progress = run.progress || {};
      const total = Math.max(Number(progress.total || 1), 1);
      const current = Math.max(Number(progress.current || 0), 0);
      const percent = Math.max(0, Math.min(100, (current / total) * 100));
      document.getElementById('progressFill').style.width = `${percent}%`;
      document.getElementById('progressText').textContent =
        `${progress.label || run.stage || 'Waiting'} ${current}/${total}`;
    }

    function renderArtifacts(artifacts) {
      const labels = {
        spanGraphUrl: 'Span graph',
        shotStyleFragmentsUrl: 'Span enrichment',
        renderPlanUrl: 'Render plan',
        multimodalDecisionsUrl: 'Photo choices',
        previewVideoUrl: 'Preview',
        finalVideoUrl: 'Final',
        finalVideoBucketUrl: 'Final bucket',
        logUrl: 'Log',
      };
      const links = Object.entries(labels)
        .filter(([key]) => artifacts[key])
        .map(([key, label]) => `<a href="${artifacts[key]}" target="_blank" rel="noreferrer">${label}</a>`);
      document.getElementById('artifactLinks').innerHTML = links.join('') || '<span style="color:var(--muted);font-size:13px">No artifacts yet.</span>';
    }

    function renderFinalVideo(artifacts) {
      const url = artifacts.finalVideoUrl || artifacts.finalVideoBucketUrl;
      if (!url) {
        const container = document.getElementById('finalVideo');
        container.textContent = 'No final video yet.';
        return;
      }
      renderVideo(url);
    }

    function renderVideo(url) {
      document.getElementById('finalVideo').innerHTML =
        `<video src="${escapeHtml(url)}" controls preload="metadata"></video>`;
    }

    async function loadSpanGraph(url) {
      const response = await fetch(url);
      if (!response.ok) return;
      const graph = await response.json();
      renderSpanMap(graph);
    }

    function renderSpanMap(graph) {
      const spans = Array.isArray(graph.span_graph) ? graph.span_graph : [];
      const duration = Number(graph.video_summary?.estimated_duration_seconds)
        || Math.max(...spans.map(span => Number(span.timeRange?.end || 0)), 1);
      const byType = {};
      for (const span of spans) {
        const type = span.type || 'unknown';
        if (!byType[type]) byType[type] = [];
        byType[type].push(span);
      }
      const order = ['whole_video', 'music_phrase', 'property_section', 'shot_group', 'shot', 'transition', 'micro_event', 'unknown'];
      const colors = {
        whole_video: '#475569',
        music_phrase: '#7c3aed',
        property_section: '#0f766e',
        shot_group: '#2563eb',
        shot: '#0ea5e9',
        transition: '#d97706',
        micro_event: '#be123c',
        unknown: '#64748b',
      };
      const html = order
        .filter(type => byType[type])
        .map(type => {
          const bars = byType[type].map(span => {
            const start = Math.max(0, Number(span.timeRange?.start || 0));
            const end = Math.max(start, Number(span.timeRange?.end || start));
            const left = Math.max(0, Math.min(100, (start / duration) * 100));
            const width = Math.max(.35, Math.min(100 - left, ((end - start) / duration) * 100));
            const label = escapeHtml(span.id || span.summary || type);
            const title = escapeHtml(`${span.id || ''} ${start.toFixed(2)}-${end.toFixed(2)}s\n${span.summary || ''}`);
            return `<div class="span" title="${title}" style="left:${left}%;width:${width}%;background:${colors[type] || colors.unknown}">${label}</div>`;
          }).join('');
          return `<div class="track"><div class="track-name">${type}</div><div class="track-line">${bars}</div></div>`;
        })
        .join('');
      document.getElementById('spanMap').innerHTML = html || '<p style="color:var(--muted)">Waiting for span graph.</p>';
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
    }

    function formatBytes(value) {
      const bytes = Number(value || 0);
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
      return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    }
  </script>
</body>
</html>"""
