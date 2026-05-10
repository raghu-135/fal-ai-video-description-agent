from __future__ import annotations

import html
import json
import logging
from functools import partial
from pathlib import Path
from uuid import uuid4

from nicegui import run, ui

from src.app.ui.pages.autohdr import best_compile_shot_count, best_generation_shot_count, count_shot_spans, read_upload_event
from src.app.ui.pages.autohdr import generated_clip_paths
from src.app.ui.pages.timeline_utils import extract_json_object, normalize_spans

logger = logging.getLogger(__name__)


def _set_result_json(editor, payload: dict) -> None:
    editor.properties["content"]["json"] = payload
    editor.update()


def build_dashboard_page(fal_service, template_store, autohdr_service=None):
    timeline_id = f"timeline-{uuid4().hex}"
    timeline_event_id = f"timeline-event-{uuid4().hex}"
    templates = template_store.list_templates()
    template_map = {t["name"]: t["prompt"] for t in templates if "name" in t and "prompt" in t}

    timeline_payload_state = {
        "video": {"url": "", "duration_ms": 0},
        "spans": [],
        "ui": {
            "initial_zoom": 0.02,
            "min_zoom_ms_per_px": 0.0005,
            "max_zoom_ms_per_px": 0.5,
            "event_target_id": timeline_event_id,
            "video_element_id": "dashboard-video-player",
        },
    }
    autohdr_state: dict[str, object] = {"photos": [], "run": None, "describe_output": None}

    def on_manage_templates():
        ui.navigate.to('/templates')

    def on_view_history():
        ui.navigate.to('/history')

    async def ensure_timeline_script() -> bool:
        return bool(
            await ui.run_javascript(
                """
                (async function() {
                  if (window.timelineWidget) return true;
                  const existing = document.querySelector('script[data-timeline-widget="1"]');
                  if (!existing) {
                    const s = document.createElement('script');
                    s.src = '/static/js/timeline_widget.js?v=4';
                    s.async = false;
                    s.dataset.timelineWidget = '1';
                    document.head.appendChild(s);
                  }
                  for (let i = 0; i < 20; i += 1) {
                    if (window.timelineWidget) return true;
                    await new Promise((r) => setTimeout(r, 50));
                  }
                  return !!window.timelineWidget;
                })();
                """
            )
        )

    async def push_timeline_payload() -> None:
        ready = await ensure_timeline_script()
        if not ready:
            timeline_status.set_text("timeline script failed to load")
            return
        payload_json = json.dumps(timeline_payload_state)
        await ui.run_javascript(
            f"window.timelineWidget && window.timelineWidget.initWithRetry('{timeline_id}', {payload_json}, 20, 50);"
        )

    def apply_track_selection(selected_tracks: list[str] | None = None) -> None:
        tracks = sorted({s["track"] for s in timeline_payload_state["spans"]})
        if not tracks:
            track_filter.options = []
            track_filter.value = []
            track_filter.update()
            timeline_status.set_text("0 spans across 0 tracks")
            ui.run_javascript(f"window.timelineWidget && window.timelineWidget.setTracks('{timeline_id}', []);")
            return

        chosen = selected_tracks if selected_tracks else tracks
        valid = [t for t in chosen if t in tracks]
        if not valid:
            valid = tracks

        track_filter.options = tracks
        track_filter.value = valid
        track_filter.update()
        timeline_status.set_text(f"{len(timeline_payload_state['spans'])} spans across {len(tracks)} tracks")
        selected_json = json.dumps(valid)
        ui.run_javascript(f"window.timelineWidget && window.timelineWidget.setTracks('{timeline_id}', {selected_json});")

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Professional Video Description").classes("text-2xl font-bold text-center")

        with ui.row().classes("w-full justify-center gap-3 pt-2"):
            ui.button("Manage Prompts", on_click=on_manage_templates).classes("px-4 py-2 bg-blue-500 text-white")
            ui.button("View History", on_click=on_view_history).classes("px-4 py-2 bg-green-500 text-white")

        with ui.column().classes("w-full gap-4"):
            video_url = ui.input("Video URL (direct media URL preferred)").classes("w-full")
            model_choice = ui.select(
                options={"default": "Default Model", "gemini_pro": "Gemini Pro"},
                value="default",
                label="Describe Model",
            ).classes("w-full")
            temperature = ui.number("Temperature (0.0 - 2.0)", value=0.1, min=0.0, max=2.0, step=0.1).classes("w-full")

            with ui.column().classes("w-full gap-4"):
                with ui.column().classes("w-full gap-2"):
                    ui.label("Prompt Input").classes("text-sm font-semibold")
                    prompt = ui.textarea("Prompt", value="Describe this video in detail.").classes("w-full min-h-[120px]")
                    prompt.on_value_change(lambda: update_prompt_preview())
                with ui.card().classes("w-full p-3 gap-3"):
                    ui.label("Template Tools").classes("text-sm font-semibold")
                    template_select = ui.select(
                        options=list(template_map.keys()),
                        label="Insert Template",
                    ).classes("w-full")
                    save_template_name = ui.input("Save Current Prompt As Template").classes("w-full")
                with ui.column().classes("w-full gap-2"):
                    ui.label("Prompt Preview").classes("text-sm font-semibold")
                    prompt_preview = ui.markdown("Describe this video in detail.").classes("w-full border rounded-lg p-4 min-h-[120px] bg-gray-50")

    def update_prompt_preview():
        if prompt.value:
            prompt_preview.set_content(prompt.value)
        else:
            prompt_preview.set_content("")

    def refresh_template_options():
        latest_templates = template_store.list_templates()
        latest_template_map = {
            t["name"]: t["prompt"] for t in latest_templates if "name" in t and "prompt" in t
        }
        template_map.clear()
        template_map.update(latest_template_map)
        template_select.options = list(template_map.keys())
        template_select.update()

    def on_template_change():
        name = template_select.value
        if name in template_map:
            prompt.value = template_map[name]
            update_prompt_preview()

    def on_save_template():
        template_name = (save_template_name.value or "").strip()
        prompt_text = (prompt.value or "").strip()
        if not template_name:
            ui.notify("Template name is required", color="negative")
            return
        if not prompt_text:
            ui.notify("Prompt cannot be empty", color="negative")
            return
        if template_name in template_map:
            template_store.update_template(template_name, {"prompt": prompt_text})
            ui.notify(f"Updated template: {template_name}", color="positive")
        else:
            template_store.create_template({"name": template_name, "prompt": prompt_text, "category": "general"})
            ui.notify(f"Saved template: {template_name}", color="positive")
        refresh_template_options()
        template_select.value = template_name
        template_select.update()

    template_select.on_value_change(on_template_change)
    with ui.row().classes("w-full justify-start"):
        ui.button("Save Prompt", on_click=on_save_template).classes("px-4 py-2")

    with ui.column().classes("w-full gap-3"):
        ui.label("Results").classes("text-lg font-semibold")
        result_json_editor = ui.json_editor({'content': {'json': {}}}).classes("w-full")

    with ui.column().classes("w-full gap-2"):
        ui.label("Timeline").classes("text-lg font-semibold")
        ui.html(
            "<video id='dashboard-video-player' controls preload='metadata' style='width:100%;max-height:360px;background:#111;border-radius:8px'></video>"
        ).classes("w-full")
        track_filter = ui.select(options=[], value=[], with_input=False, multiple=True, label="Visible Tracks").classes("w-full")
        timeline_status = ui.label("0 spans across 0 tracks").classes("text-xs text-gray-600")
        timeline_html = ui.html(
            f"""
            <div id=\"{timeline_id}\" style=\"position:relative;width:100%;min-height:220px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;background:#f9fafb\">\n
              <canvas></canvas>\n
              <div data-role=\"empty\" style=\"position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#6b7280;font-size:13px\">No spans available yet. Run a description first.</div>\n
              <div data-role=\"tooltip\" style=\"display:none;position:absolute;pointer-events:none;background:#111827;color:#fff;padding:6px 8px;border-radius:6px;font-size:12px;white-space:nowrap;z-index:10\"></div>\n
            </div>
            """
        ).classes("w-full")
        timeline_event = ui.element("div").props(f"id={timeline_event_id}")

    def set_autohdr_json(payload: dict) -> None:
        autohdr_json_editor.properties["content"]["json"] = payload
        autohdr_json_editor.update()

    def autohdr_file_url(path_value: str | None) -> str | None:
        manifest = autohdr_state.get("run")
        if not manifest or not path_value or autohdr_service is None:
            return None
        assert isinstance(manifest, dict)
        run_id = manifest["id"]
        run_dir = autohdr_service.run_dir(run_id).resolve()
        path = Path(path_value).resolve()
        try:
            relative = path.relative_to(run_dir)
        except ValueError:
            return None
        return f"/api/autohdr/runs/{run_id}/files/{relative.as_posix()}"

    def set_autohdr_busy(is_busy: bool, label: str = "Working...") -> None:
        set_button_enabled(autohdr_create_button, not is_busy and bool(autohdr_service))
        has_run = isinstance(autohdr_state.get("run"), dict)
        has_plan = bool((autohdr_state.get("run") or {}).get("artifacts", {}).get("renderPlan")) if has_run else False
        set_button_enabled(autohdr_compile_button, not is_busy and has_run)
        set_button_enabled(autohdr_generate_button, not is_busy and has_plan)
        autohdr_spinner.set_visibility(is_busy)
        autohdr_busy_label.set_visibility(is_busy)
        autohdr_busy_label.set_text(label)

    def best_autohdr_compile_shot_count() -> int | None:
        describe_output = autohdr_state.get("describe_output")
        if isinstance(describe_output, dict):
            count = count_shot_spans(describe_output)
            if count:
                return count
        manifest = autohdr_state.get("run")
        return best_compile_shot_count(manifest) if isinstance(manifest, dict) else None

    def update_autohdr_max_controls() -> None:
        compile_count = best_autohdr_compile_shot_count()
        manifest = autohdr_state.get("run")
        generation_count = best_generation_shot_count(manifest) if isinstance(manifest, dict) else None
        autohdr_compile_max_button.set_text(f"Max ({compile_count})" if compile_count else "Max")
        autohdr_generation_max_button.set_text(f"Max ({generation_count})" if generation_count else "Max")
        set_button_enabled(autohdr_compile_max_button, bool(compile_count))
        set_button_enabled(autohdr_generation_max_button, bool(generation_count))

    def set_autohdr_compile_max_to_best() -> None:
        count = best_autohdr_compile_shot_count()
        if not count:
            ui.notify("Run Describe Now first so the full shot count is available", color="warning")
            return
        autohdr_max_shots.set_value(count)

    def set_autohdr_generation_max_to_best() -> None:
        manifest = autohdr_state.get("run")
        count = best_generation_shot_count(manifest) if isinstance(manifest, dict) else None
        if not count:
            ui.notify("Compile the AutoHDR plan first so the full timeline count is known", color="warning")
            return
        autohdr_generation_max_shots.set_value(count)

    def refresh_autohdr_manifest(manifest: dict) -> None:
        autohdr_state["run"] = manifest
        autohdr_status.set_text(f"Status: {manifest.get('status', '-')}")
        autohdr_run_label.set_text(f"Run: {manifest.get('id', '-')}")
        autohdr_summary.set_text(
            f"Photos: {manifest.get('photoCount', 0)} | "
            f"Shots: {manifest.get('timelineShotCount', 0) or 0}"
            + (f" | {manifest.get('durationTarget')}s" if manifest.get("durationTarget") else "")
        )
        progress = manifest.get("generationProgress") if isinstance(manifest.get("generationProgress"), dict) else {}
        if progress:
            autohdr_progress.set_text(
                f"Generation: {progress.get('stage', '-')} | "
                f"{progress.get('generatedShotCount', 0)}/{progress.get('totalShotCount', 0)} clips"
            )
        else:
            autohdr_progress.set_text("Generation: not started")
        error = manifest.get("error")
        autohdr_error.set_text(error.get("message", "") if isinstance(error, dict) else "")
        autohdr_error.set_visibility(bool(error))
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        autohdr_artifact_select.options = list(artifacts.keys())
        autohdr_artifact_select.update()
        set_autohdr_json(manifest)
        update_autohdr_max_controls()
        update_autohdr_final_video(manifest)
        update_autohdr_generated_clips(manifest)
        set_autohdr_busy(False)

    def update_autohdr_final_video(manifest: dict) -> None:
        autohdr_final_video.clear()
        progress = manifest.get("generationProgress") if isinstance(manifest.get("generationProgress"), dict) else {}
        video_url = manifest.get("finalVideoUrl") or progress.get("finalVideoUrl")
        with autohdr_final_video:
            if not isinstance(video_url, str) or not video_url:
                ui.label("No composed final video yet.").classes("text-sm text-gray-500")
                return
            src = html.escape(video_url, quote=True)
            ui.html(
                f"""
                <video src="{src}" controls preload="metadata" style="width:100%;max-height:420px;background:#111;border-radius:8px"></video>
                """
            ).classes("w-full")

    def update_autohdr_generated_clips(manifest: dict) -> None:
        autohdr_generated_clips.clear()
        clips = generated_clip_paths(manifest)
        with autohdr_generated_clips:
            if not clips:
                ui.label("No Fal clips generated yet.").classes("text-sm text-gray-500")
                return
            for clip in clips:
                source = autohdr_file_url(str(clip))
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

    async def on_autohdr_upload(event) -> None:
        name, content = await read_upload_event(event)
        photos = autohdr_state["photos"]
        assert isinstance(photos, list)
        photos.append((name, content))
        refresh_autohdr_photo_queue()

    def clear_autohdr_photos() -> None:
        autohdr_state["photos"] = []
        refresh_autohdr_photo_queue()

    def refresh_autohdr_photo_queue() -> None:
        photos = autohdr_state["photos"]
        assert isinstance(photos, list)
        count = len(photos)
        autohdr_photo_label.set_text(f"{count} photo{'s' if count != 1 else ''} queued")
        autohdr_photo_list.clear()
        with autohdr_photo_list:
            if not photos:
                ui.label("No destination photos selected yet.").classes("text-sm text-gray-500")
                return
            for name, content in photos[:12]:
                ui.label(f"{name} · {len(content) // 1024} KB").classes("text-sm text-gray-700")
            if len(photos) > 12:
                ui.label(f"+ {len(photos) - 12} more").classes("text-sm text-gray-500")

    async def on_autohdr_create_run() -> None:
        if autohdr_service is None:
            ui.notify("AutoHDR service is unavailable", color="negative")
            return
        url = (video_url.value or "").strip()
        photos = autohdr_state["photos"]
        describe_output = autohdr_state.get("describe_output")
        if not url:
            ui.notify("Enter the describe video URL first", color="negative")
            return
        if not isinstance(describe_output, dict):
            ui.notify("Run Describe Now first so AutoHDR can reuse the describe response", color="negative")
            return
        if not photos:
            ui.notify("Upload destination photos first", color="negative")
            return
        set_autohdr_busy(True, "Creating AutoHDR run...")
        try:
            manifest = await run.io_bound(autohdr_service.create_run, url, photos, describe_output)
            refresh_autohdr_manifest(manifest)
            ui.notify("AutoHDR run created from describe output", color="positive")
        except Exception as exc:
            ui.notify(str(exc), color="negative")
            set_autohdr_busy(False)

    async def on_autohdr_compile() -> None:
        manifest = autohdr_state.get("run")
        if autohdr_service is None or not isinstance(manifest, dict):
            ui.notify("Create an AutoHDR run first", color="negative")
            return
        set_autohdr_busy(True, "Compiling AutoHDR plan...")
        try:
            updated = await run.io_bound(
                partial(
                    autohdr_service.compile_run,
                    manifest["id"],
                    multimodal=autohdr_multimodal.value,
                    max_shots=int(autohdr_max_shots.value) if autohdr_max_shots.value else None,
                )
            )
            refresh_autohdr_manifest(updated)
            ui.notify("AutoHDR plan compiled", color="positive")
        except Exception as exc:
            refresh_autohdr_manifest(autohdr_service.get_run(manifest["id"]))
            ui.notify(str(exc), color="negative")

    async def on_autohdr_generate() -> None:
        manifest = autohdr_state.get("run")
        if autohdr_service is None or not isinstance(manifest, dict):
            return
        set_autohdr_busy(True, "Generating AutoHDR Fal clips and composing final video...")
        try:
            updated = await run.io_bound(
                partial(
                    autohdr_service.generate_final_run,
                    manifest["id"],
                    resolution=autohdr_resolution.value,
                    max_shots=int(autohdr_generation_max_shots.value) if autohdr_generation_max_shots.value else None,
                    parallelism=int(autohdr_parallelism.value) if autohdr_parallelism.value is not None else 1,
                )
            )
            refresh_autohdr_manifest(updated)
            ui.notify("AutoHDR final video generated", color="positive")
        except Exception as exc:
            refresh_autohdr_manifest(autohdr_service.get_run(manifest["id"]))
            ui.notify(str(exc), color="negative")

    def on_autohdr_artifact_change() -> None:
        manifest = autohdr_state.get("run")
        if not isinstance(manifest, dict):
            return
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        path = artifacts.get(autohdr_artifact_select.value)
        if not path:
            set_autohdr_json(manifest)
            return
        try:
            set_autohdr_json(json.loads(Path(path).read_text(encoding="utf-8")))
        except Exception as exc:
            set_autohdr_json({"error": str(exc), "path": path})

    def on_autohdr_refresh() -> None:
        manifest = autohdr_state.get("run")
        if autohdr_service is None or not isinstance(manifest, dict):
            ui.notify("No AutoHDR run to refresh", color="warning")
            return
        try:
            refresh_autohdr_manifest(autohdr_service.get_run(manifest["id"]))
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    def on_autohdr_load_latest() -> None:
        if autohdr_service is None:
            ui.notify("AutoHDR service is unavailable", color="negative")
            return
        runs = autohdr_service.list_runs()
        if not runs:
            ui.notify("No AutoHDR runs found", color="warning")
            return
        refresh_autohdr_manifest(runs[0])
        ui.notify(f"Loaded AutoHDR run {runs[0].get('id')}", color="positive")

    action_buttons_row = ui.row().classes("w-full justify-center gap-3 pt-4")

    with ui.column().classes("w-full gap-3"):
        ui.label("AutoHDR Pipeline").classes("text-lg font-semibold")
        with ui.card().classes("w-full p-4 gap-3"):
            ui.label("Uses the latest parsed Describe Now response and this page's video URL as the reference.").classes("text-sm text-gray-600")
            with ui.row().classes("w-full justify-between items-center"):
                ui.label("Destination Photos").classes("font-semibold")
                ui.button("Clear Photos", on_click=clear_autohdr_photos).classes("px-3 py-1")
            ui.upload(
                label="Choose Photos or Drop Images Here",
                on_upload=on_autohdr_upload,
                multiple=True,
                auto_upload=True,
            ).props("accept=image/* color=primary").classes("w-full")
            autohdr_photo_label = ui.label("0 photos queued").classes("text-sm text-gray-600")
            autohdr_photo_list = ui.column().classes("w-full gap-1")

            with ui.row().classes("w-full gap-3 items-center"):
                autohdr_multimodal = ui.checkbox("Multimodal photo compile", value=True)
                autohdr_max_shots = ui.number("Compile max shots", value=None, min=1, step=1).classes("w-48")
                autohdr_compile_max_button = ui.button("Max", on_click=set_autohdr_compile_max_to_best).classes("px-3 py-2")
                autohdr_compile_max_button.tooltip(
                    "Set compile max shots to every shot from the describe response. This preserves the full reference timeline."
                )
                autohdr_resolution = ui.select(["480p", "720p", "1080p"], value="720p", label="Fal clip resolution").classes("w-48")
                autohdr_generation_max_shots = ui.number("Generation max shots", value=None, min=1, step=1).classes("w-48")
                autohdr_generation_max_button = ui.button("Max", on_click=set_autohdr_generation_max_to_best).classes("px-3 py-2")
                autohdr_generation_max_button.tooltip(
                    "Set generation max shots to every compiled timeline shot. This is the accurate full-length final video setting."
                )
                autohdr_parallelism = ui.number("Parallelism", value=1, min=0, step=1).classes("w-40")
                autohdr_parallelism.tooltip(
                    "How many Fal shot pipelines to run concurrently. 1 is sequential. 3 runs three shots at once. 0 means all selected shots at once; use carefully for rate limits and cost."
                )
                ui.button("Max", on_click=lambda: autohdr_parallelism.set_value(0)).classes("px-3 py-2").tooltip(
                    "Set parallelism to 0, which runs all selected Fal shot jobs concurrently."
                )

            with ui.row().classes("w-full gap-3 items-center"):
                autohdr_create_button = ui.button("Create AutoHDR Run", on_click=on_autohdr_create_run).classes("px-4 py-2")
                autohdr_compile_button = ui.button("Compile Plan", on_click=on_autohdr_compile).classes("px-4 py-2")
                autohdr_generate_button = ui.button("Generate Final Video", on_click=on_autohdr_generate).classes("px-4 py-2")
                ui.button("Load Latest Run", on_click=on_autohdr_load_latest).classes("px-4 py-2")
                ui.button("Refresh Status", on_click=on_autohdr_refresh).classes("px-4 py-2")
                autohdr_spinner = ui.spinner(size="md")
                autohdr_busy_label = ui.label("Working...").classes("text-sm text-gray-600")

            autohdr_run_label = ui.label("Run: -").classes("font-semibold")
            autohdr_status = ui.label("Status: waiting for describe response")
            autohdr_summary = ui.label("Photos: 0 | Shots: 0")
            autohdr_progress = ui.label("Generation: not started")
            autohdr_error = ui.label("").classes("text-red-600")
            ui.label("Final Video").classes("font-semibold")
            autohdr_final_video = ui.column().classes("w-full gap-2")
            ui.label("Generated Fal Clips").classes("font-semibold")
            autohdr_generated_clips = ui.column().classes("w-full gap-4")
            autohdr_artifact_select = ui.select(options=[], label="AutoHDR Artifact").classes("w-full")
            autohdr_json_editor = ui.json_editor({"content": {"json": {}}}).classes("w-full")
            autohdr_artifact_select.on_value_change(on_autohdr_artifact_change)

    autohdr_compile_button.disable()
    autohdr_generate_button.disable()
    autohdr_compile_max_button.disable()
    autohdr_generation_max_button.disable()
    autohdr_spinner.set_visibility(False)
    autohdr_busy_label.set_visibility(False)
    autohdr_error.set_visibility(False)

    def on_track_filter_change():
        selected = track_filter.value or []
        apply_track_selection(selected)

    track_filter.on_value_change(on_track_filter_change)

    with ui.row().classes("w-full items-center justify-center gap-3 py-2"):
        processing_spinner = ui.spinner(size="lg")
        processing_spinner.set_visibility(False)
        processing_label = ui.label("Processing video...").classes("text-gray-600")
        processing_label.set_visibility(False)

    def set_processing(is_processing: bool) -> None:
        describe_button.enabled = not is_processing
        processing_spinner.set_visibility(is_processing)
        processing_label.set_visibility(is_processing)

    def sync_video_source() -> None:
        safe_url = json.dumps(video_url.value or "")
        ui.run_javascript(
            f"""
            (function() {{
              const player = document.getElementById('dashboard-video-player');
              if (!player) return;
              if (player.src !== {safe_url}) {{
                player.src = {safe_url};
              }}
            }})();
            """
        )

    async def refresh_video_duration() -> None:
        duration_ms = await ui.run_javascript(
            """
            (function() {
              const player = document.getElementById('dashboard-video-player');
              if (!player || !isFinite(player.duration)) return 0;
              return Math.floor(player.duration * 1000);
            })();
            """
        )
        timeline_payload_state["video"] = {
            "url": video_url.value or "",
            "duration_ms": int(duration_ms or 0),
        }

    async def on_describe():
        if not video_url.value:
            ui.notify("Enter a video URL", color="negative")
            return

        sync_video_source()
        set_processing(True)
        try:
            result = await run.io_bound(
                fal_service.describe_video_from_url,
                video_url.value,
                prompt.value,
                temperature.value,
                model_choice.value,
            )
            logger.info("Dashboard describe result payload: %s", result)
            template_store.append_history(
                {
                    "mode": "describe",
                    "source": video_url.value,
                    "prompt": prompt.value,
                    "model_choice": model_choice.value,
                    "result": result,
                }
            )
            output_text = result.get("output", "")

            try:
                parsed_json = extract_json_object(output_text)
                autohdr_state["describe_output"] = parsed_json
                autohdr_status.set_text("Status: describe response ready for AutoHDR")
                update_autohdr_max_controls()

                _set_result_json(result_json_editor, parsed_json)

                spans = normalize_spans(parsed_json)
                await refresh_video_duration()
                timeline_payload_state["spans"] = spans
                await push_timeline_payload()
                apply_track_selection()
                await ui.run_javascript("new Promise(r => setTimeout(r, 80));")
                apply_track_selection(track_filter.value)
                dbg = await ui.run_javascript(f"window.timelineWidget && window.timelineWidget.debug('{timeline_id}')")
                if isinstance(dbg, dict):
                    timeline_status.set_text(
                        f"{len(spans)} spans across {len(set(s['track'] for s in spans))} tracks | widget spans: {dbg.get('payloadSpanCount', 0)}"
                    )
                ui.notify(f"Timeline updated with {len(spans)} spans", color="positive")

            except (json.JSONDecodeError, KeyError) as e:
                _set_result_json(
                    result_json_editor,
                    {
                        "error": f"Failed to parse JSON: {str(e)}",
                        "raw_response": result,
                        "output_text": output_text,
                    },
                )
                timeline_payload_state["spans"] = []
                autohdr_state["describe_output"] = None
                autohdr_status.set_text("Status: describe response is not valid JSON")
                update_autohdr_max_controls()
                await push_timeline_payload()
                apply_track_selection()
        except Exception as exc:
            error_text = str(exc)
            _set_result_json(
                result_json_editor,
                {
                    "error": "Describe request failed",
                    "message": error_text,
                    "raw_error": repr(exc),
                    "video_url": video_url.value,
                    "prompt_length": len(prompt.value or ""),
                },
            )
            ui.notify(str(exc), color="negative")
            autohdr_state["describe_output"] = None
            autohdr_status.set_text("Status: describe request failed")
            update_autohdr_max_controls()
        finally:
            set_processing(False)

    def on_submit():
        try:
            if not video_url.value:
                ui.notify("Enter a video URL", color="negative")
                return
            handle = fal_service.submit_video_from_url(video_url.value, prompt.value)
            _set_result_json(
                result_json_editor,
                {
                    "message": "Request submitted",
                    "request_id": getattr(handle, "request_id", ""),
                    "status_url": getattr(handle, "status_url", None),
                    "response_url": getattr(handle, "response_url", None),
                },
            )
        except Exception as exc:
            _set_result_json(
                result_json_editor,
                {
                    "error": "Submit request failed",
                    "message": str(exc),
                    "raw_error": repr(exc),
                    "video_url": video_url.value,
                    "prompt_length": len(prompt.value or ""),
                },
            )
            ui.notify(str(exc), color="negative")

    async def on_timeline_seek(event):
        payload = event.args or {}
        time_ms = int(payload.get("time_ms", 0))
        time_seconds = max(0, time_ms / 1000.0)
        await ui.run_javascript(
            f"""
            (function() {{
              const player = document.getElementById('dashboard-video-player');
              if (!player) return;
              player.currentTime = {time_seconds};
            }})();
            """
        )

    def on_timeline_hover(event):
        _ = event.args or {}

    timeline_event.on("timeline_seek", on_timeline_seek)
    timeline_event.on("timeline_hover", on_timeline_hover)

    ui.timer(
        0.1,
        lambda: ui.run_javascript(
            f"""
            (function() {{
              const player = document.getElementById('dashboard-video-player');
              if (!player || !isFinite(player.currentTime)) return;
              window.timelineWidget && window.timelineWidget.setPlayhead('{timeline_id}', Math.floor(player.currentTime * 1000));
            }})();
            """
        ),
    )


    async def initialize_timeline_once() -> None:
        await push_timeline_payload()
        dbg = await ui.run_javascript(f"window.timelineWidget && window.timelineWidget.debug('{timeline_id}')")
        if isinstance(dbg, dict) and dbg.get("ready"):
            timeline_status.set_text("0 spans across 0 tracks | widget ready")

    ui.timer(0.2, initialize_timeline_once, once=True)

    with action_buttons_row:
        describe_button = ui.button("Describe Now", on_click=on_describe).classes("px-6 py-2")
        ui.button("Submit Async", on_click=on_submit).classes("px-6 py-2")


def set_button_enabled(button, enabled: bool) -> None:
    if enabled:
        button.enable()
    else:
        button.disable()
