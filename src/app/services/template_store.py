from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: str, default: Any):
        self.path = Path(path)
        self.default = default

    def load(self):
        if self.path.exists() and self.path.is_dir():
            return self.default
        if not self.path.exists():
            return self.default
        with self.path.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return self.default

    def save(self, data: Any) -> None:
        if self.path.exists() and self.path.is_dir():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


class TemplateStore:
    def __init__(self, templates_path: str, history_path: str):
        self.templates_store = JsonStore(templates_path, default=[])
        self.history_store = JsonStore(history_path, default=[])

    def list_templates(self) -> list[dict[str, Any]]:
        return self.templates_store.load()

    def create_template(self, template: dict[str, Any]) -> dict[str, Any]:
        templates = self.list_templates()
        templates.append(template)
        self.templates_store.save(templates)
        return template

    def update_template(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        templates = self.list_templates()
        for idx, tmpl in enumerate(templates):
            if tmpl.get("name") == name:
                templates[idx] = {**tmpl, **payload}
                self.templates_store.save(templates)
                return templates[idx]
        raise KeyError(f"Template not found: {name}")

    def delete_template(self, name: str) -> bool:
        templates = self.list_templates()
        filtered = [t for t in templates if t.get("name") != name]
        changed = len(filtered) != len(templates)
        if changed:
            self.templates_store.save(filtered)
        return changed

    def append_history(self, entry: dict[str, Any]) -> None:
        history = self.history_store.load()
        history.append(entry)
        self.history_store.save(history)

    def list_history(self) -> list[dict[str, Any]]:
        return self.history_store.load()
