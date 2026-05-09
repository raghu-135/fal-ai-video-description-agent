from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from nicegui import ui

from src.app.api.templates import router as template_router
from src.app.api.video import router as video_router
from src.app.main_deps import get_fal_service, get_template_store
from src.app.ui.pages.dashboard import build_dashboard_page
from src.app.ui.pages.history import build_history_page
from src.app.ui.pages.templates import build_templates_page

app = FastAPI(title="Professional Video Description API")
app.include_router(video_router)
app.include_router(template_router)
logging.basicConfig(level=logging.INFO)
#logging.getLogger("httpx").setLevel(logging.DEBUG)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1")
def v1_ui_redirect():
    return RedirectResponse(url="/", status_code=307)


@app.get("/v1/health")
def v1_health():
    return {"status": "ok"}


@ui.page("/")
def dashboard_page():
    build_dashboard_page(get_fal_service(), get_template_store())


@ui.page("/templates")
def templates_page():
    build_templates_page(get_template_store())


@ui.page("/history")
def history_page():
    build_history_page(get_template_store())


ui.run_with(app, mount_path="/")
