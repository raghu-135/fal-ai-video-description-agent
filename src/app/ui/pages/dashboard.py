from __future__ import annotations

import json
import logging

from nicegui import run, ui

logger = logging.getLogger(__name__)


def _set_result_json(editor, payload: dict) -> None:
    editor.properties["content"]["json"] = payload
    editor.update()


def build_dashboard_page(fal_service, template_store):
    templates = template_store.list_templates()
    template_map = {t["name"]: t["prompt"] for t in templates if "name" in t and "prompt" in t}

    # Define functions first
    def on_manage_templates():
        ui.navigate.to('/templates')

    def on_view_history():
        ui.navigate.to('/history')

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Professional Video Description").classes("text-2xl font-bold text-center")
        
        # Navigation buttons at the top
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
        """Update the markdown preview with the current prompt content."""
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
                
                _set_result_json(result_json_editor, parsed_json)
                
            except (json.JSONDecodeError, KeyError) as e:
                _set_result_json(
                    result_json_editor,
                    {
                        "error": f"Failed to parse JSON: {str(e)}",
                        "raw_response": result,
                        "output_text": output_text,
                    },
                )
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

    with ui.row().classes("w-full justify-center gap-3 pt-4"):
        describe_button = ui.button("Describe Now", on_click=on_describe).classes("px-6 py-2")
        ui.button("Submit Async", on_click=on_submit).classes("px-6 py-2")
