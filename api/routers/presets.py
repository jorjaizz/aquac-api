"""Precomputed crop-rotation presets."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from api.services.presets import (
    PresetError,
    PresetNotFound,
    get_preset,
    list_presets,
    precompute_preset,
)
from api.services.simulation import SimulationError
from api.settings import get_settings

router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("", summary="List rotation presets")
def presets() -> dict:
    try:
        return {"presets": list_presets()}
    except PresetError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{slug}", summary="Get a preset and its precomputed result")
def preset(slug: str) -> dict:
    try:
        return get_preset(slug)
    except PresetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PresetError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/{slug}/recompute",
    summary="Recompute a preset and store the result",
)
def recompute(
    slug: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    settings = get_settings()
    if not settings.admin_token:
        raise HTTPException(
            status_code=403,
            detail="ADMIN_TOKEN is not configured; recompute is disabled.",
        )
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")

    try:
        return precompute_preset(slug)
    except PresetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PresetError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
