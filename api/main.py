"""FastAPI application entry point.

Run locally with::

    uvicorn api.main:app --reload

The app exposes the AquaCrop-OSPy model as HTTP endpoints so that other
services (e.g. the VoidHarvest dashboard) can consume it without importing
the model directly.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import catalog, health, presets, simulations

app = FastAPI(
    title="AquaCrop-OSPy API",
    description=(
        "HTTP wrapper around AquaCrop-OSPy for crop-water simulations. "
        "Built for the VoidHarvest / NASA Space Apps 2026 project."
    ),
    version="0.1.0",
)

_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
if not _origins:
    _origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(simulations.router)
app.include_router(presets.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {
        "service": "AquaCrop-OSPy API",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/catalog/crops",
            "/catalog/soils",
            "/catalog/weather-files",
            "/catalog/co2-scenarios",
            "/simulate",
            "/simulate/rotation",
            "/simulate/planting-dates",
            "/presets",
            "/presets/{slug}",
            "/presets/{slug}/simulate",
        ],
    }
