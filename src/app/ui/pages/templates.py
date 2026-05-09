from __future__ import annotations

from nicegui import ui


def build_templates_page(template_store):
    ui.label("Prompt Templates").classes("text-2xl font-bold")

    name = ui.input("Template name")
    prompt = ui.textarea("Template prompt")
    category = ui.input("Category", value="general")

    rows = ui.column()

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
        refresh_rows()

    def delete_template(template_name: str):
        template_store.delete_template(template_name)
        refresh_rows()

    ui.button("Save Template", on_click=create_template)
    refresh_rows()
