from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.app.main_deps import get_fal_service, get_template_store

router = APIRouter(prefix="/api/video", tags=["video"])


@router.post("/describe")
async def describe_video(
    video_url: str | None = Form(default=None),
    prompt: str = Form(default="Describe this video in detail."),
    model_choice: str = Form(),
    file: UploadFile | None = File(default=None),
    fal_service=Depends(get_fal_service),
    template_store=Depends(get_template_store),
):
    try:
        if video_url:
            result = fal_service.describe_video_from_url(video_url, prompt, model_choice=model_choice)
            source = video_url
        elif file:
            tmp_path = f"/tmp/{file.filename}"
            with open(tmp_path, "wb") as f:
                f.write(await file.read())
            result = fal_service.describe_video_from_file(tmp_path, prompt, model_choice=model_choice)
            source = file.filename
        else:
            raise HTTPException(status_code=400, detail="Provide video_url or file")

        template_store.append_history(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "describe",
                "source": source,
                "prompt": prompt,
                "model_choice": model_choice,
                "result": result,
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/submit")
async def submit_video(
    video_url: str | None = Form(default=None),
    prompt: str = Form(default="Describe this video in detail."),
    webhook_url: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    fal_service=Depends(get_fal_service),
):
    try:
        if video_url:
            handle = fal_service.submit_video_from_url(video_url, prompt, webhook_url)
        elif file:
            tmp_path = f"/tmp/{file.filename}"
            with open(tmp_path, "wb") as f:
                f.write(await file.read())
            handle = fal_service.submit_video_from_file(tmp_path, prompt, webhook_url)
        else:
            raise HTTPException(status_code=400, detail="Provide video_url or file")

        return {
            "request_id": getattr(handle, "request_id", None),
            "status_url": getattr(handle, "status_url", None),
            "response_url": getattr(handle, "response_url", None),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{request_id}/status")
def get_status(request_id: str, fal_service=Depends(get_fal_service)):
    try:
        return fal_service.get_request_status(request_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{request_id}/result")
def get_result(request_id: str, fal_service=Depends(get_fal_service)):
    try:
        return fal_service.get_request_result(request_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
