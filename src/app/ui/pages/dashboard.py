from __future__ import annotations

import json
import logging
from uuid import uuid4

from nicegui import run, ui

from src.app.ui.pages.timeline_utils import extract_json_object, normalize_spans

logger = logging.getLogger(__name__)


def _set_result_json(editor, payload: dict) -> None:
    editor.properties["content"]["json"] = payload
    editor.update()


def build_dashboard_page(fal_service, template_store):
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
                    s.src = '/static/js/timeline_widget.js?v=3';
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
            ui.button("Manage Templates", on_click=on_manage_templates).classes("px-4 py-2 bg-blue-500 text-white")
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
        ui.button("Save Template", on_click=on_save_template).classes("px-4 py-2")

    with ui.column().classes("w-full gap-3"):
        ui.label("Results").classes("text-lg font-semibold")
        result_json_editor = ui.json_editor({'content': {'json': {}}}).classes("w-full")

    with ui.column().classes("w-full gap-2"):
        ui.label("Timeline").classes("text-lg font-semibold")
        ui.html(
            "<video id='dashboard-video-player' controls preload='metadata' style='width:100%;max-height:360px;background:#111;border-radius:8px'></video>"
        ).classes("w-full")
        with ui.row().classes("w-full items-center gap-2"):
            ui.button("-", on_click=lambda: ui.run_javascript(f"window.timelineWidget && window.timelineWidget.zoomOut('{timeline_id}')")).classes("px-3")
            ui.button("+", on_click=lambda: ui.run_javascript(f"window.timelineWidget && window.timelineWidget.zoomIn('{timeline_id}')")).classes("px-3")
            ui.button("Reset", on_click=lambda: ui.run_javascript(f"window.timelineWidget && window.timelineWidget.reset('{timeline_id}')")).classes("px-3")
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

    with ui.row().classes("w-full justify-center gap-3 pt-4"):
        describe_button = ui.button("Describe Now", on_click=on_describe).classes("px-6 py-2")
        ui.button("Submit Async", on_click=on_submit).classes("px-6 py-2")
