from functools import lru_cache

from src.app.core.config import get_settings
from src.app.services.fal_service import FalVideoService
from src.app.services.template_store import TemplateStore


@lru_cache(maxsize=1)
def get_fal_service() -> FalVideoService:
    return FalVideoService(get_settings())


@lru_cache(maxsize=1)
def get_template_store() -> TemplateStore:
    settings = get_settings()
    return TemplateStore(settings.prompt_templates_path, settings.processing_history_path)
