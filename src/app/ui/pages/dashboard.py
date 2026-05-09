from __future__ import annotations

import json
import logging

from nicegui import run, ui

logger = logging.getLogger(__name__)


def build_dashboard_page(fal_service, template_store):
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Professional Video Description").classes("text-2xl font-bold text-center")

        with ui.column().classes("w-full gap-4"):
            video_url = ui.input("Video URL (direct media URL preferred)").classes("w-full")
            
            with ui.column().classes("w-full gap-4"):
                with ui.column().classes("w-full gap-2"):
                    ui.label("Prompt Input").classes("text-sm font-semibold")
                    prompt = ui.textarea("Prompt", value="Describe this video in detail.").classes("w-full min-h-[120px]")
                    prompt.on_value_change(lambda: update_prompt_preview())
                with ui.column().classes("w-full gap-2"):
                    ui.label("Prompt Preview").classes("text-sm font-semibold")
                    prompt_preview = ui.markdown("Describe this video in detail.").classes("w-full border rounded-lg p-4 min-h-[120px] bg-gray-50")

    def update_prompt_preview():
        """Update the markdown preview with the current prompt content."""
        if prompt.value:
            prompt_preview.set_content(prompt.value)
        else:
            prompt_preview.set_content("")

    templates = template_store.list_templates()
    template_map = {t["name"]: t["prompt"] for t in templates if "name" in t and "prompt" in t}
    if template_map:
        template_select = ui.select(options=list(template_map.keys()), label="Prompt Template").classes("w-full")

        def on_template_change():
            name = template_select.value
            if name in template_map:
                prompt.value = template_map[name]
                update_prompt_preview()

        template_select.on_value_change(on_template_change)

    with ui.column().classes("w-full gap-3"):
        ui.label("Results").classes("text-lg font-semibold")
        result_json_editor = ui.json_editor({'content': {'json': {}}}).classes("w-full")

    with ui.row().classes("w-full items-center justify-center gap-3 py-2"):
        processing_spinner = ui.spinner(size="lg")
        processing_spinner.set_visibility(False)
        processing_label = ui.label("Processing video...").classes("text-gray-600")
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
            # Extract JSON from response (handle markdown wrapping)
            output_text = result.get("output", "")
            
            try:
                # Remove markdown code blocks if present
                if output_text.startswith("```json"):
                    json_text = output_text.strip().replace("```json", "").replace("```", "")
                    parsed_json = json.loads(json_text)
                elif output_text.startswith("```"):
                    json_text = output_text.strip().replace("```", "")
                    parsed_json = json.loads(json_text)
                else:
                    # Try to parse as-is
                    parsed_json = json.loads(output_text)
                
                result_json_editor.properties['content']['json'] = parsed_json
                
            except (json.JSONDecodeError, KeyError) as e:
                result_json_editor.properties['content']['json'] = {
                    'error': f'Failed to parse JSON: {str(e)}',
                    'raw_response': result,
                    'output_text': output_text
                }
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
            result_json_editor.properties['content']['json'] = {
                'message': f"Request Submitted\n\nRequest ID: {getattr(handle, 'request_id', '')}"
            }
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    with ui.row().classes("w-full justify-center gap-3 pt-4"):
        describe_button = ui.button("Describe Now", on_click=on_describe).classes("px-6 py-2")
        ui.button("Submit Async", on_click=on_submit).classes("px-6 py-2")
