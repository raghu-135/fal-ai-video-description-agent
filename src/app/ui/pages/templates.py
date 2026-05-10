from __future__ import annotations

from nicegui import ui


def build_templates_page(template_store):
    with ui.column().classes("w-full gap-4"):
        # Navigation header
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("Prompt Templates").classes("text-2xl font-bold")
            ui.button("← Back to Dashboard", on_click=lambda: ui.navigate.to('/')).classes("px-4 py-2 bg-gray-500 text-white")

    # Define functions first
        def refresh_editor():
            templates = template_store.list_templates()
            templates_editor.properties['content']['json'] = templates

        def refresh_rows():
            rows.clear()
            with rows:
                for t in template_store.list_templates():
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"{t.get('name')} ({t.get('category', 'general')})")
                        ui.button("Delete", on_click=lambda e, n=t.get("name"): delete_template(n))

        def create_template():
            if not name.value or not prompt.value:
                ui.notify("Name and prompt required", color="negative")
                return
            template_store.create_template({"name": name.value, "prompt": prompt.value, "category": category.value})
            ui.notify("Template saved", color="positive")
            refresh_editor()
            refresh_rows()

        def delete_template(template_name: str):
            template_store.delete_template(template_name)
            refresh_editor()
            refresh_rows()

        # Template creation form
        with ui.card().classes("w-full p-4"):
            ui.label("Create New Template").classes("text-lg font-semibold mb-3")
            name = ui.input("Template name")
            prompt = ui.textarea("Template prompt")
            category = ui.input("Category", value="general")
            ui.button("Save Template", on_click=create_template).classes("mt-2")

        # Templates display with JSON editor
        with ui.column().classes("w-full gap-2"):
            ui.label("All Templates").classes("text-lg font-semibold")
            templates_editor = ui.json_editor({'content': {'json': []}}).classes("w-full min-h-[400px]")
            
            # Simple template list for actions
            rows = ui.column()

        # Initialize displays
        refresh_editor()
        refresh_rows()
