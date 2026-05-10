from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.app.main_deps import get_autohdr_service

router = APIRouter(prefix="/api/autohdr", tags=["autohdr"])


@router.post("/runs")
async def create_run(
    reference_video_url: str = Form(...),
    describe_output_json: str | None = Form(default=None),
    photos: list[UploadFile] = File(...),
    autohdr_service=Depends(get_autohdr_service),
):
    try:
        uploaded = [(photo.filename or "photo.jpg", await photo.read()) for photo in photos]
        describe_output = json.loads(describe_output_json) if describe_output_json else None
        return autohdr_service.create_run(reference_video_url, uploaded, describe_output=describe_output)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
def list_runs(autohdr_service=Depends(get_autohdr_service)):
    return autohdr_service.list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str, autohdr_service=Depends(get_autohdr_service)):
    try:
        return autohdr_service.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/compile")
def compile_run(
    run_id: str,
    multimodal: bool = Form(default=True),
    max_shots: int | None = Form(default=None),
    multimodal_parallelism: int = Form(default=3),
    autohdr_service=Depends(get_autohdr_service),
):
    try:
        return autohdr_service.compile_run(
            run_id,
            multimodal=multimodal,
            max_shots=max_shots,
            multimodal_parallelism=multimodal_parallelism,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/generate")
def generate_final(
    run_id: str,
    resolution: str = Form(default="720p"),
    max_shots: int | None = Form(default=None),
    parallelism: int = Form(default=3),
    download_generated_clips: bool = Form(default=False),
    autohdr_service=Depends(get_autohdr_service),
):
    try:
        return autohdr_service.generate_final_run(
            run_id,
            resolution=resolution,
            max_shots=max_shots,
            parallelism=parallelism,
            download_generated_clips=download_generated_clips,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/files/{relative_path:path}")
def get_file(run_id: str, relative_path: str, autohdr_service=Depends(get_autohdr_service)):
    try:
        path = autohdr_service.artifact_path(run_id, relative_path)
        return FileResponse(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
