from __future__ import annotations

from nicegui import ui


def build_history_page(template_store):
    ui.label("Processing History").classes("text-2xl font-bold")
    history = template_store.list_history()
    if not history:
        ui.label("No history yet")
        return

    for item in reversed(history[-50:]):
        with ui.card().classes("w-full"):
            ui.label(f"Source: {item.get('source', 'unknown')}")
            ui.label(f"Prompt: {item.get('prompt', '')}")
            result = item.get("result", {})
            description = result.get("data", {}).get("description", "") if isinstance(result, dict) else ""
            ui.markdown(description[:500] if description else "No description found")
