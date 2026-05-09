from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.main_deps import get_template_store

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplatePayload(BaseModel):
    name: str
    prompt: str
    category: str = "general"


@router.get("")
def list_templates(store=Depends(get_template_store)):
    return store.list_templates()


@router.post("")
def create_template(payload: TemplatePayload, store=Depends(get_template_store)):
    return store.create_template(payload.model_dump())


@router.put("/{name}")
def update_template(name: str, payload: TemplatePayload, store=Depends(get_template_store)):
    try:
        return store.update_template(name, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{name}")
def delete_template(name: str, store=Depends(get_template_store)):
    if not store.delete_template(name):
        raise HTTPException(status_code=404, detail=f"Template not found: {name}")
    return {"deleted": True}


@router.get("/history")
def list_history(store=Depends(get_template_store)):
    return store.list_history()
