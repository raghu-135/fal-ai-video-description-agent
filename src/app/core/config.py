import os
from dataclasses import dataclass


@dataclass
class Settings:
    fal_key: str
    fal_model: str = "fal-ai/video-understanding"
    fal_describe_model: str = "google/gemini-2.5-pro"
    fal_describe_app: str = "openrouter/router/video"
    prompt_templates_path: str = "data/prompt_templates.json"
    processing_history_path: str = "data/processing_history.json"
    autohdr_runs_path: str = "data/autohdr_runs"



def get_settings() -> Settings:
    fal_key = os.getenv("FAL_KEY", "").strip() or load_env_value("FAL_KEY")
    if not fal_key:
        raise ValueError(
            "FAL_KEY environment variable not set. "
            "Please set your Fal AI API key."
        )
    return Settings(fal_key=fal_key)


def load_env_value(key: str, path: str = ".env") -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return ""
