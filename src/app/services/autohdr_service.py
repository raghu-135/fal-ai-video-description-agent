from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from autohdr_pipeline.ai_style_template import build_ai_style_template
from autohdr_pipeline.compiler import compile_render_plan
from autohdr_pipeline.generation import IMAGE_EDIT_ENDPOINT, VIDEO_ENDPOINT_QUALITY, compose_fal_video, generate_fal_clips
from autohdr_pipeline.multimodal_compiler import run_multimodal_compile
from autohdr_pipeline.photo_inventory import analyze_photoshoot
from autohdr_pipeline.pipeline import fetch_fal_span_graph
from autohdr_pipeline.utils import write_json
from src.app.core.config import Settings


class AutoHDRService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = Path(settings.autohdr_runs_path)

    def create_run(
        self,
        reference_video_url: str,
        photos: list[tuple[str, bytes]],
        describe_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reference_video_url = reference_video_url.strip()
        if not reference_video_url:
            raise ValueError("Reference video URL is required.")
        if not photos:
            raise ValueError("Upload at least one destination photo.")

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        run_dir = self.run_dir(run_id)
        photos_dir = run_dir / "inputs" / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)

        photo_records = []
        for index, (filename, content) in enumerate(photos, 1):
            safe_name = sanitize_filename(filename, fallback=f"photo_{index:03d}.jpg")
            path = photos_dir / f"{index:03d}_{safe_name}"
            path.write_bytes(content)
            photo_records.append({"filename": safe_name, "path": str(path), "sizeBytes": len(content)})

        artifacts: dict[str, str] = {}
        if describe_output:
            describe_path = run_dir / "inputs" / "describe_output.json"
            write_json(describe_path, describe_output)
            artifacts["describeOutput"] = str(describe_path)

        manifest = {
            "schema": "autohdr_run.v1",
            "id": run_id,
            "status": "created",
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
            "referenceVideoUrl": reference_video_url,
            "referenceVideoPath": None,
            "photosDir": str(photos_dir),
            "photoCount": len(photo_records),
            "photos": photo_records,
            "artifacts": artifacts,
            "error": None,
        }
        self.save_manifest(run_id, manifest)
        return manifest

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        runs = []
        for path in sorted(self.root.iterdir(), reverse=True):
            manifest_path = path / "manifest.json"
            if manifest_path.exists():
                runs.append(self.with_disk_generation_progress(load_json(manifest_path)))
        return runs

    def get_run(self, run_id: str) -> dict[str, Any]:
        manifest_path = self.manifest_path(run_id)
        if not manifest_path.exists():
            raise FileNotFoundError(f"AutoHDR run not found: {run_id}")
        return self.with_disk_generation_progress(load_json(manifest_path))

    def compile_run(
        self,
        run_id: str,
        *,
        multimodal: bool = True,
        max_shots: int | None = None,
        multimodal_max_candidates: int = 8,
    ) -> dict[str, Any]:
        manifest = self.mark_status(run_id, "compiling")
        output_dir = self.output_dir(run_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            reference = self.ensure_reference_video(run_id)
            photos_dir = Path(manifest["photosDir"])
            style_filename = "reference_style_template.ai.json"
            render_plan_filename = "render_plan.ai.json"

            parsed = None
            describe_output_path = manifest.get("artifacts", {}).get("describeOutput")
            if describe_output_path:
                parsed = load_json(Path(describe_output_path))
                write_json(output_dir / "fal_span_graph.parsed.json", parsed)
            else:
                parsed = fetch_fal_span_graph(
                    reference,
                    output_dir,
                    manifest["referenceVideoUrl"],
                    self.settings.fal_describe_app,
                    self.settings.fal_describe_model,
                    64000,
                    0.2,
                )
            if parsed is None:
                raise RuntimeError("Fal video understanding did not return parseable JSON.")
            style = build_ai_style_template(parsed, reference, max_shots=max_shots)
            write_json(output_dir / style_filename, style)

            inventory = analyze_photoshoot(photos_dir, use_filename_profile=False)
            plan = compile_render_plan(style, inventory)
            write_json(output_dir / "photo_inventory.local.json", inventory)
            write_json(output_dir / render_plan_filename, plan)
            self.save_compile_artifacts(
                run_id,
                output_dir,
                style_filename,
                render_plan_filename,
                plan,
                status="compiled_ai_plan",
            )

            if multimodal:
                self.mark_status(run_id, "multimodal_compiling")
                plan = run_multimodal_compile(
                    plan,
                    output_dir,
                    model=self.settings.fal_describe_model,
                    max_candidates=multimodal_max_candidates,
                    max_shots=max_shots,
                )
                render_plan_filename = "render_plan.ai.multimodal.json"
                write_json(output_dir / render_plan_filename, plan)

            return self.save_compile_artifacts(run_id, output_dir, style_filename, render_plan_filename, plan, status="compiled")
        except Exception as exc:
            self.mark_error(run_id, exc)
            raise

    def generate_final_run(
        self,
        run_id: str,
        *,
        resolution: str = "720p",
        max_shots: int | None = None,
        parallelism: int = 1,
    ) -> dict[str, Any]:
        manifest = self.mark_status(run_id, "generating")
        try:
            plan = load_json(Path(manifest["artifacts"]["renderPlan"]))
            generation_dir = self.output_dir(run_id)
            total = len(plan["timeline"][:max_shots] if max_shots else plan["timeline"])
            self.update_generation_progress(
                run_id,
                {
                    "stage": "starting",
                    "generatedShotCount": count_generated_clips(generation_dir),
                    "totalShotCount": total,
                },
            )
            result = generate_fal_clips(
                plan,
                generation_dir,
                video_model=VIDEO_ENDPOINT_QUALITY,
                image_edit_model=IMAGE_EDIT_ENDPOINT,
                resolution=resolution,
                max_shots=max_shots,
                parallelism=parallelism,
                progress_callback=lambda progress: self.update_generation_progress(run_id, progress),
            )
            self.update_generation_progress(
                run_id,
                {
                    "stage": "composing",
                    "generatedShotCount": result["shotCount"],
                    "totalShotCount": result["shotCount"],
                    "generatedClipsDir": str(generation_dir / "generated"),
                },
            )
            composition = compose_fal_video(
                result,
                generation_dir,
                reference_video_url=manifest.get("referenceVideoUrl"),
                include_reference_audio=False,
            )
            manifest = self.get_run(run_id)
            manifest["artifacts"]["generationManifest"] = str(generation_dir / "generation_manifest.json")
            manifest["artifacts"]["compositionManifest"] = str(generation_dir / "composition_manifest.json")
            manifest["finalVideoUrl"] = composition["finalVideoUrl"]
            manifest["finalVideoThumbnailUrl"] = composition.get("thumbnailUrl")
            manifest["generationProgress"] = {
                "stage": "done",
                "generatedShotCount": result["shotCount"],
                "totalShotCount": result["shotCount"],
                "generatedClipsDir": str(generation_dir / "generated"),
                "finalVideoUrl": composition["finalVideoUrl"],
            }
            return self.save_manifest(run_id, mark_manifest(manifest, "generated"))
        except Exception as exc:
            self.mark_error(run_id, exc)
            raise

    def artifact_path(self, run_id: str, relative_path: str) -> Path:
        base = self.run_dir(run_id).resolve()
        path = (base / relative_path).resolve()
        if base != path and base not in path.parents:
            raise ValueError("Artifact path is outside the run directory.")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(relative_path)
        return path

    def save_compile_artifacts(
        self,
        run_id: str,
        output_dir: Path,
        style_filename: str,
        render_plan_filename: str,
        plan: dict[str, Any],
        *,
        status: str,
    ) -> dict[str, Any]:
        manifest = self.get_run(run_id)
        manifest["artifacts"].update(
            {
                "styleTemplate": str(output_dir / style_filename),
                "photoInventory": str(output_dir / "photo_inventory.local.json"),
                "renderPlan": str(output_dir / render_plan_filename),
            }
        )
        if (output_dir / "fal_span_graph.parsed.json").exists():
            manifest["artifacts"]["spanGraph"] = str(output_dir / "fal_span_graph.parsed.json")
        if (output_dir / "multimodal_compiler_decisions.json").exists():
            manifest["artifacts"]["multimodalDecisions"] = str(output_dir / "multimodal_compiler_decisions.json")
        manifest["timelineShotCount"] = len(plan.get("timeline", []))
        manifest["durationTarget"] = plan.get("durationTarget")
        return self.save_manifest(run_id, mark_manifest(manifest, status))

    def ensure_reference_video(self, run_id: str) -> Path:
        manifest = self.get_run(run_id)
        existing = manifest.get("referenceVideoPath")
        if isinstance(existing, str) and Path(existing).exists():
            return Path(existing)

        parsed = urllib.parse.urlparse(manifest["referenceVideoUrl"])
        suffix = Path(parsed.path).suffix.lower()
        if not suffix:
            suffix = mimetypes.guess_extension(mimetypes.guess_type(parsed.path)[0] or "") or ".mp4"
        if suffix not in {".mp4", ".mov", ".webm", ".mkv"}:
            suffix = ".mp4"

        path = self.run_dir(run_id) / "inputs" / f"reference{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(manifest["referenceVideoUrl"], headers={"User-Agent": "curl/8.0.0"})
        with urllib.request.urlopen(request, timeout=240) as response:
            path.write_bytes(response.read())
        manifest["referenceVideoPath"] = str(path)
        self.save_manifest(run_id, manifest)
        return path

    def run_dir(self, run_id: str) -> Path:
        safe_run_id = sanitize_run_id(run_id)
        if safe_run_id != run_id:
            raise ValueError("Invalid AutoHDR run id.")
        return self.root / safe_run_id

    def output_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "outputs"

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def save_manifest(self, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["updatedAt"] = now_iso()
        path = self.manifest_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    def mark_status(self, run_id: str, status: str) -> dict[str, Any]:
        manifest = self.get_run(run_id)
        manifest["status"] = status
        manifest["error"] = None
        return self.save_manifest(run_id, manifest)

    def mark_error(self, run_id: str, exc: Exception) -> dict[str, Any]:
        manifest = self.get_run(run_id)
        manifest["status"] = "error"
        manifest["error"] = {"message": str(exc), "type": type(exc).__name__}
        return self.save_manifest(run_id, manifest)

    def update_generation_progress(self, run_id: str, progress: dict[str, Any]) -> None:
        manifest = self.get_run(run_id)
        manifest["status"] = "generating"
        manifest["generationProgress"] = {**manifest.get("generationProgress", {}), **progress, "updatedAt": now_iso()}
        artifacts = manifest.setdefault("artifacts", {})
        if isinstance(artifacts, dict):
            artifacts["generatedClipsDir"] = str(self.output_dir(run_id) / "generated")
        self.save_manifest(run_id, manifest)

    def with_disk_generation_progress(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if manifest.get("generationProgress"):
            return manifest
        run_id = manifest.get("id")
        if not isinstance(run_id, str):
            return manifest
        output_dir = self.output_dir(run_id)
        generated_count = count_generated_clips(output_dir)
        if generated_count <= 0:
            return manifest
        total = manifest.get("timelineShotCount") or generated_count
        manifest["generationProgress"] = {
            "stage": "clips_exist",
            "generatedShotCount": generated_count,
            "totalShotCount": total,
            "updatedAt": manifest.get("updatedAt"),
        }
        artifacts = manifest.setdefault("artifacts", {})
        if isinstance(artifacts, dict):
            artifacts["generatedClipsDir"] = str(output_dir / "generated")
        return manifest


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_manifest(manifest: dict[str, Any], status: str) -> dict[str, Any]:
    manifest["status"] = status
    manifest["error"] = None
    return manifest


def count_generated_clips(output_dir: Path) -> int:
    generated_dir = output_dir / "generated"
    if not generated_dir.exists():
        return 0
    return sum(1 for path in generated_dir.glob("*.mp4") if path.is_file())


def sanitize_filename(filename: str, *, fallback: str) -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def sanitize_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "", run_id or "")
