from __future__ import annotations

from nicegui import ui


def build_history_page(template_store):
    with ui.column().classes("w-full gap-4"):
        # Navigation header
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("Processing History").classes("text-2xl font-bold")
            ui.button("← Back to Dashboard", on_click=lambda: ui.navigate.to('/')).classes("px-4 py-2 bg-gray-500 text-white")
        # History display with JSON editor
        with ui.column().classes("w-full gap-2"):
            ui.label("Processing History (JSON View)").classes("text-lg font-semibold")
            history_editor = ui.json_editor({'content': {'json': []}}).classes("w-full min-h-[400px]")
            
            # Card view for recent history
            ui.label("Recent History (Card View)").classes("text-lg font-semibold")
            cards_container = ui.column().classes("w-full gap-2")

        def refresh_history():
            history = template_store.list_history()
            # Update JSON editor with all history
            history_editor.properties['content']['json'] = history
            
            # Update card view with recent 50 items
            cards_container.clear()
            with cards_container:
                if not history:
                    ui.label("No history yet").classes("text-gray-500")
                else:
                    for item in reversed(history[-50:]):
                        with ui.card().classes("w-full p-4"):
                            ui.label(f"Source: {item.get('source', 'unknown')}").classes("font-semibold")
                            ui.label(f"Prompt: {item.get('prompt', '')}").classes("text-sm text-gray-600")
                            result = item.get("result", {})
                            description = result.get("data", {}).get("description", "") if isinstance(result, dict) else ""
                            ui.markdown(description[:500] if description else "No description found").classes("text-sm")

        # Initialize history display
        refresh_history()
