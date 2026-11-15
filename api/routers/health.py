"""Health and service metadata endpoints."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": "AquaCrop-OSPy",
        "version": "3.1.0",
    }
