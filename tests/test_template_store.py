from src.app.services.template_store import TemplateStore


def test_template_crud(tmp_path):
    templates = tmp_path / "prompt_templates.json"
    history = tmp_path / "processing_history.json"
    store = TemplateStore(str(templates), str(history))

    created = store.create_template({"name": "default", "prompt": "Describe", "category": "general"})
    assert created["name"] == "default"

    listed = store.list_templates()
    assert len(listed) == 1

    updated = store.update_template("default", {"prompt": "New prompt"})
    assert updated["prompt"] == "New prompt"

    deleted = store.delete_template("default")
    assert deleted is True
    assert store.list_templates() == []
