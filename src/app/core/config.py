import os
from dataclasses import dataclass


@dataclass
class Settings:
    fal_key: str
    fal_model: str = "fal-ai/video-understanding"
    prompt_templates_path: str = "data/prompt_templates.json"
    processing_history_path: str = "data/processing_history.json"



def get_settings() -> Settings:
    fal_key = os.getenv("FAL_KEY", "").strip()
    if not fal_key:
        raise ValueError(
            "FAL_KEY environment variable not set. "
            "Please set your Fal AI API key."
        )
    return Settings(fal_key=fal_key)
