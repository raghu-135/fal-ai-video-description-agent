from __future__ import annotations

import html
import json
import inspect
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import run, ui


def build_autohdr_page(autohdr_service, reference_url: str = ""):
    state: dict[str, Any] = {"run": None, "photos": []}

    def file_url(path_value: str | None) -> str | None:
        manifest = state.get("run")
        if not manifest or not path_value:
            return None
        run_id = manifest["id"]
        run_dir = autohdr_service.run_dir(run_id).resolve()
        path = Path(path_value).resolve()
        try:
            relative = path.relative_to(run_dir)
        except ValueError:
            return None
        return f"/api/autohdr/runs/{run_id}/files/{relative.as_posix()}"

    def set_json(payload: dict[str, Any]) -> None:
        artifact_editor.properties["content"]["json"] = payload
        artifact_editor.update()

    def refresh_from_manifest(manifest: dict[str, Any]) -> None:
        state["run"] = manifest
        run_id_label.set_text(f"Run: {manifest.get('id', '-')}")
        status_label.set_text(f"Status: {manifest.get('status', '-')}")
        photo_count_label.set_text(f"Photos: {manifest.get('photoCount', 0)}")
        shot_count = manifest.get("timelineShotCount")
        duration = manifest.get("durationTarget")
        summary_label.set_text(
            f"Timeline: {shot_count or 0} shots"
            + (f" | {duration}s" if duration else "")
        )
        progress = manifest.get("generationProgress") if isinstance(manifest.get("generationProgress"), dict) else {}
        if progress:
            progress_label.set_text(
                f"Generation: {progress.get('stage', '-')} | "
                f"{progress.get('generatedShotCount', 0)}/{progress.get('totalShotCount', 0)} clips"
            )
        else:
            progress_label.set_text("Generation: not started")
        error = manifest.get("error")
        error_label.set_text(error.get("message", "") if isinstance(error, dict) else "")
        error_label.set_visibility(bool(error))
        set_json(manifest)
        compile_button.enable()
        set_button_enabled(generate_button, bool(manifest.get("artifacts", {}).get("renderPlan")))
        load_artifact_options()
        update_max_controls()
        update_final_video()
        update_generated_clips()

    def load_artifact_options() -> None:
        manifest = state.get("run") or {}
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        artifact_select.options = list(artifacts.keys())
        artifact_select.update()

    def update_generated_clips() -> None:
        generated_clips.clear()
        manifest = state.get("run") or {}
        clips = generated_clip_paths(manifest)
        with generated_clips:
            if not clips:
                ui.label("No Fal clips generated yet.").classes("text-sm text-gray-500")
                return
            for clip in clips:
                source = file_url(str(clip))
                if not source:
                    continue
                label = html.escape(clip.stem)
                src = html.escape(source, quote=True)
                ui.html(
                    f"""
                    <div style="display:grid;gap:6px">
                      <div style="font-size:13px;font-weight:600;color:#374151">{label}</div>
                      <video src="{src}" controls preload="metadata" style="width:100%;max-height:300px;background:#111;border-radius:8px"></video>
                    </div>
                    """
                ).classes("w-full")

    def update_final_video() -> None:
        final_video.clear()
        manifest = state.get("run") or {}
        progress = manifest.get("generationProgress") if isinstance(manifest.get("generationProgress"), dict) else {}
        video_url = manifest.get("finalVideoUrl") or progress.get("finalVideoUrl")
        with final_video:
            if not isinstance(video_url, str) or not video_url:
                ui.label("No composed final video yet.").classes("text-sm text-gray-500")
                return
            src = html.escape(video_url, quote=True)
            ui.html(
                f"""
                <video src="{src}" controls preload="metadata" style="width:100%;max-height:420px;background:#111;border-radius:8px"></video>
                """
            ).classes("w-full")

    def set_busy(is_busy: bool, label: str = "Working...") -> None:
        set_button_enabled(create_button, not is_busy)
        set_button_enabled(compile_button, not is_busy and bool(state.get("run")))
        set_button_enabled(generate_button, not is_busy and bool((state.get("run") or {}).get("artifacts", {}).get("renderPlan")))
        spinner.set_visibility(is_busy)
        busy_label.set_visibility(is_busy)
        busy_label.set_text(label)

    def update_max_controls() -> None:
        manifest = state.get("run") or {}
        compile_count = best_compile_shot_count(manifest)
        generation_count = best_generation_shot_count(manifest)
        compile_max_button.set_text(f"Max ({compile_count})" if compile_count else "Max")
        generation_max_button.set_text(f"Max ({generation_count})" if generation_count else "Max")
        set_button_enabled(compile_max_button, bool(compile_count))
        set_button_enabled(generation_max_button, bool(generation_count))

    def set_compile_max_to_best() -> None:
        count = best_compile_shot_count(state.get("run") or {})
        if not count:
            ui.notify("No described shot count is available yet", color="warning")
            return
        max_shots.set_value(count)

    def set_generation_max_to_best() -> None:
        count = best_generation_shot_count(state.get("run") or {})
        if not count:
            ui.notify("Compile the plan first so the full timeline count is known", color="warning")
            return
        generation_max_shots.set_value(count)

    async def on_upload(event) -> None:
        name, content = await read_upload_event(event)
        state["photos"].append((name, content))
        refresh_photo_queue()

    def clear_photos() -> None:
        state["photos"] = []
        refresh_photo_queue()

    def refresh_photo_queue() -> None:
        count = len(state["photos"])
        photo_upload_label.set_text(f"{count} photo{'s' if count != 1 else ''} queued")
        photos_list.clear()
        with photos_list:
            if not state["photos"]:
                ui.label("No destination photos selected yet.").classes("text-sm text-gray-500")
                return
            for name, content in state["photos"][:12]:
                ui.label(f"{name} · {len(content) // 1024} KB").classes("text-sm text-gray-700")
            if len(state["photos"]) > 12:
                ui.label(f"+ {len(state['photos']) - 12} more").classes("text-sm text-gray-500")

    async def on_create_run() -> None:
        url = (reference_input.value or "").strip()
        if not url:
            ui.notify("Reference video URL is required", color="negative")
            return
        if not state["photos"]:
            ui.notify("Upload at least one photo", color="negative")
            return
        set_busy(True, "Creating run...")
        try:
            manifest = await run.io_bound(autohdr_service.create_run, url, state["photos"])
            refresh_from_manifest(manifest)
            ui.notify("AutoHDR run created", color="positive")
        except Exception as exc:
            ui.notify(str(exc), color="negative")
        finally:
            set_busy(False)

    async def on_compile() -> None:
        manifest = state.get("run")
        if not manifest:
            ui.notify("Create a run first", color="negative")
            return
        set_busy(True, "Compiling spans and render plan...")
        try:
            updated = await run.io_bound(
                partial(
                    autohdr_service.compile_run,
                    manifest["id"],
                    multimodal=multimodal_toggle.value,
                    max_shots=int(max_shots.value) if max_shots.value else None,
                    multimodal_parallelism=int(multimodal_parallelism.value) if multimodal_parallelism.value is not None else 3,
                )
            )
            refresh_from_manifest(updated)
            ui.notify("Render plan compiled", color="positive")
        except Exception as exc:
            latest = autohdr_service.get_run(manifest["id"])
            refresh_from_manifest(latest)
            ui.notify(str(exc), color="negative")
        finally:
            set_busy(False)

    async def on_generate() -> None:
        manifest = state.get("run")
        if not manifest:
            return
        set_busy(True, "Generating Fal clips and composing final video...")
        try:
            updated = await run.io_bound(
                partial(
                    autohdr_service.generate_final_run,
                    manifest["id"],
                    resolution=resolution.value,
                    max_shots=int(generation_max_shots.value) if generation_max_shots.value else None,
                    parallelism=int(parallelism.value) if parallelism.value is not None else 3,
                    download_generated_clips=bool(download_generated_clips.value),
                )
            )
            refresh_from_manifest(updated)
            ui.notify("Final AutoHDR video generated", color="positive")
        except Exception as exc:
            latest = autohdr_service.get_run(manifest["id"])
            refresh_from_manifest(latest)
            ui.notify(str(exc), color="negative")
        finally:
            set_busy(False)

    def on_artifact_change() -> None:
        manifest = state.get("run") or {}
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        path = artifacts.get(artifact_select.value)
        if not path:
            set_json(manifest)
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            payload = {"error": str(exc), "path": path}
        set_json(payload)

    def on_refresh_status() -> None:
        manifest = state.get("run")
        if not manifest:
            ui.notify("No AutoHDR run to refresh", color="warning")
            return
        try:
            refresh_from_manifest(autohdr_service.get_run(manifest["id"]))
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    def on_load_latest_run() -> None:
        runs = autohdr_service.list_runs()
        if not runs:
            ui.notify("No AutoHDR runs found", color="warning")
            return
        refresh_from_manifest(runs[0])
        ui.notify(f"Loaded AutoHDR run {runs[0].get('id')}", color="positive")

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("AutoHDR Pipeline").classes("text-2xl font-bold")
            ui.button("Back to Dashboard", on_click=lambda: ui.navigate.to("/")).classes("px-4 py-2")

        with ui.column().classes("w-full gap-3"):
            reference_input = ui.input("Reference Video URL", value=reference_url or "").classes("w-full")
            with ui.card().classes("w-full p-4 gap-3"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label("Destination Photos").classes("text-lg font-semibold")
                    ui.button("Clear Photos", on_click=clear_photos).classes("px-3 py-1")
                ui.upload(
                    label="Choose Photos or Drop Images Here",
                    on_upload=on_upload,
                    multiple=True,
                    auto_upload=True,
                ).props("accept=image/* color=primary").classes("w-full")
                photo_upload_label = ui.label("0 photos queued").classes("text-sm text-gray-600")
                photos_list = ui.column().classes("w-full gap-1")

        with ui.row().classes("w-full gap-3 items-center"):
            multimodal_toggle = ui.checkbox("Multimodal photo compile", value=True)
            max_shots = ui.number("Compile max shots", value=None, min=1, step=1).classes("w-48")
            multimodal_parallelism = ui.number("Multimodal parallelism", value=3, min=1, step=1).classes("w-48")
            compile_max_button = ui.button("Max", on_click=set_compile_max_to_best).classes("px-3 py-2")
            compile_max_button.tooltip(
                "Set compile max shots to every shot from the describe response. This preserves the full reference timeline."
            )

        with ui.row().classes("w-full gap-3 items-center"):
            create_button = ui.button("Create Run", on_click=on_create_run).classes("px-4 py-2")
            compile_button = ui.button("Compile Plan", on_click=on_compile).classes("px-4 py-2")
            generate_button = ui.button("Generate Final Video", on_click=on_generate).classes("px-4 py-2")
            ui.button("Load Latest Run", on_click=on_load_latest_run).classes("px-4 py-2")
            ui.button("Refresh Status", on_click=on_refresh_status).classes("px-4 py-2")
            spinner = ui.spinner(size="md")
            busy_label = ui.label("Working...").classes("text-sm text-gray-600")

        with ui.row().classes("w-full gap-3 items-center"):
            resolution = ui.select(["480p", "720p", "1080p"], value="720p", label="Fal clip resolution").classes("w-48")
            generation_max_shots = ui.number("Generation max shots", value=None, min=1, step=1).classes("w-48")
            generation_max_button = ui.button("Max", on_click=set_generation_max_to_best).classes("px-3 py-2")
            generation_max_button.tooltip(
                "Set generation max shots to every compiled timeline shot. This is the accurate full-length final video setting."
            )
            parallelism = ui.number("Parallelism", value=3, min=0, step=1).classes("w-40")
            parallelism.tooltip(
                "How many Fal shot pipelines to run concurrently. 1 is sequential. 3 runs three shots at once. 0 means all selected shots at once; use carefully for rate limits and cost."
            )
            download_generated_clips = ui.checkbox("Download local clips", value=False)
            download_generated_clips.tooltip("Keeps a local .mp4 per shot for preview. Leaving this off is faster.")
            ui.button("Max", on_click=lambda: parallelism.set_value(0)).classes("px-3 py-2").tooltip(
                "Set parallelism to 0, which runs all selected Fal shot jobs concurrently."
            )

        with ui.card().classes("w-full p-4 gap-2"):
            run_id_label = ui.label("Run: -").classes("font-semibold")
            status_label = ui.label("Status: idle")
            photo_count_label = ui.label("Photos: 0")
            summary_label = ui.label("Timeline: 0 shots")
            progress_label = ui.label("Generation: not started")
            error_label = ui.label("").classes("text-red-600")

        with ui.column().classes("w-full gap-3"):
            ui.label("Final Video").classes("text-lg font-semibold")
            final_video = ui.column().classes("w-full gap-2")

        with ui.column().classes("w-full gap-3"):
            ui.label("Generated Fal Clips").classes("text-lg font-semibold")
            generated_clips = ui.column().classes("w-full gap-4")

        with ui.column().classes("w-full gap-2"):
            artifact_select = ui.select(options=[], label="Artifact").classes("w-full")
            artifact_editor = ui.json_editor({"content": {"json": {}}}).classes("w-full")
            artifact_select.on_value_change(on_artifact_change)

    compile_button.disable()
    generate_button.disable()
    compile_max_button.disable()
    generation_max_button.disable()
    spinner.set_visibility(False)
    busy_label.set_visibility(False)
    error_label.set_visibility(False)


def set_button_enabled(button, enabled: bool) -> None:
    if enabled:
        button.enable()
    else:
        button.disable()


def generated_clip_paths(manifest: dict[str, Any]) -> list[Path]:
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    clips_dir = artifacts.get("generatedClipsDir")
    if not isinstance(clips_dir, str):
        progress = manifest.get("generationProgress") if isinstance(manifest.get("generationProgress"), dict) else {}
        clips_dir = progress.get("generatedClipsDir")
    if not isinstance(clips_dir, str):
        return []
    path = Path(clips_dir)
    if not path.exists() or not path.is_dir():
        return []
    return sorted(item for item in path.glob("*.mp4") if item.is_file())


def best_compile_shot_count(manifest: dict[str, Any]) -> int | None:
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    describe_path = artifacts.get("describeOutput") if isinstance(artifacts, dict) else None
    if isinstance(describe_path, str):
        try:
            count = count_shot_spans(json.loads(Path(describe_path).read_text(encoding="utf-8")))
            if count:
                return count
        except Exception:
            pass
    span_graph_path = artifacts.get("spanGraph") if isinstance(artifacts, dict) else None
    if isinstance(span_graph_path, str):
        try:
            count = count_shot_spans(json.loads(Path(span_graph_path).read_text(encoding="utf-8")))
            if count:
                return count
        except Exception:
            pass
    return best_generation_shot_count(manifest)


def best_generation_shot_count(manifest: dict[str, Any]) -> int | None:
    count = manifest.get("timelineShotCount")
    return int(count) if isinstance(count, int) and count > 0 else None


def count_shot_spans(payload: dict[str, Any]) -> int | None:
    spans = payload.get("span_graph")
    if not isinstance(spans, list):
        return None
    count = sum(1 for span in spans if isinstance(span, dict) and span.get("type") == "shot")
    return count or None


async def read_upload_event(event) -> tuple[str, bytes]:
    upload = getattr(event, "file", None)
    if upload is not None:
        content = upload.read()
        if inspect.isawaitable(content):
            content = await content
        return getattr(upload, "name", "photo.jpg") or "photo.jpg", content

    content_source = getattr(event, "content", None)
    if content_source is None:
        raise ValueError("Upload event did not include a file payload.")
    content = content_source.read()
    if inspect.isawaitable(content):
        content = await content
    return getattr(event, "name", "photo.jpg") or "photo.jpg", content
