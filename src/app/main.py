from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from nicegui import ui

from src.app.api.autohdr import router as autohdr_router
from src.app.api.templates import router as template_router
from src.app.api.video import router as video_router
from src.app.main_deps import get_autohdr_service, get_fal_service, get_template_store
from src.app.ui.pages.autohdr import build_autohdr_page
from src.app.ui.pages.dashboard import build_dashboard_page
from src.app.ui.pages.history import build_history_page
from src.app.ui.pages.templates import build_templates_page

app = FastAPI(title="Professional Video Description API")
app.include_router(video_router)
app.include_router(template_router)
app.include_router(autohdr_router)
logging.basicConfig(level=logging.INFO)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1")
def v1_ui_redirect():
    return RedirectResponse(url="/", status_code=307)


@app.get("/v1/health")
def v1_health():
    return {"status": "ok"}


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@ui.page("/")
def dashboard_page():
    build_dashboard_page(get_fal_service(), get_template_store(), get_autohdr_service())


@ui.page("/templates")
def templates_page():
    build_templates_page(get_template_store())


@ui.page("/history")
def history_page():
    build_history_page(get_template_store())


@ui.page("/autohdr")
def autohdr_page(reference_url: str = ""):
    build_autohdr_page(get_autohdr_service(), reference_url)


ui.run_with(app, mount_path="/")
