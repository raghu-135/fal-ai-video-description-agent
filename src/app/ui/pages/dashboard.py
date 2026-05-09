from __future__ import annotations

import json
import logging

from nicegui import run, ui

logger = logging.getLogger(__name__)


def build_dashboard_page(fal_service, template_store):
    ui.label("Professional Video Description").classes("text-2xl font-bold")

    with ui.column().classes("w-full gap-3"):
        video_url = ui.input("Video URL (direct media URL preferred)").classes("w-full")
        prompt = ui.textarea("Prompt", value="Describe this video in detail.").classes("w-full")

    templates = template_store.list_templates()
    template_map = {t["name"]: t["prompt"] for t in templates if "name" in t and "prompt" in t}
    if template_map:
        template_select = ui.select(options=list(template_map.keys()), label="Prompt Template").classes("w-full")

        def on_template_change():
            name = template_select.value
            if name in template_map:
                prompt.value = template_map[name]

        template_select.on_value_change(on_template_change)

    result_box = ui.markdown("Ready.").classes("w-full")
    result_box.style(
        "white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;"
    )
    ui.add_head_html(
        """
        <style>
        .nicegui-markdown pre {
            white-space: pre-wrap !important;
            overflow-wrap: anywhere !important;
            word-break: break-word !important;
        }
        .nicegui-markdown pre code {
            white-space: inherit !important;
        }
        </style>
        """
    )

    with ui.row().classes("w-full items-center gap-3"):
        processing_spinner = ui.spinner(size="lg")
        processing_spinner.set_visibility(False)
        processing_label = ui.label("Processing video...")
        processing_label.set_visibility(False)

    def set_processing(is_processing: bool) -> None:
        describe_button.enabled = not is_processing
        processing_spinner.set_visibility(is_processing)
        processing_label.set_visibility(is_processing)

    async def on_describe():
        if not video_url.value:
            ui.notify("Enter a video URL", color="negative")
            return

        set_processing(True)
        try:
            result = await run.io_bound(
                fal_service.describe_video_from_url,
                video_url.value,
                prompt.value,
            )
            logger.info("Dashboard describe result payload: %s", result)
            template_store.append_history(
                {"mode": "describe", "source": video_url.value, "prompt": prompt.value, "result": result}
            )
            description = result.get("data", {}).get("description", "No description found")
            if description == "No description found":
                raw_payload = json.dumps(result, indent=2, default=str)
                result_box.set_content(
                    "## Result\n\n"
                    "No description found.\n\n"
                    f"### Raw Fal Response\n```json\n{raw_payload}\n```"
                )
            else:
                result_box.set_content(
                    "## Result\n\n"
                    f"### Description\n{description}"
                )
        except Exception as exc:
            ui.notify(str(exc), color="negative")
        finally:
            set_processing(False)

    def on_submit():
        try:
            if not video_url.value:
                ui.notify("Enter a video URL", color="negative")
                return
            handle = fal_service.submit_video_from_url(video_url.value, prompt.value)
            result_box.set_content(
                f"## Request Submitted\n\nRequest ID: `{getattr(handle, 'request_id', '')}`"
            )
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    with ui.row().classes("w-full gap-2"):
        describe_button = ui.button("Describe Now", on_click=on_describe)
        ui.button("Submit Async", on_click=on_submit)
