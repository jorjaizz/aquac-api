"""Read-only catalogs of built-in model options."""
from __future__ import annotations

from fastapi import APIRouter

from api.constants import CO2_SCENARIOS, SOIL_TYPES, crop_names, weather_files

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/crops")
def list_crops() -> dict:
    return {"crops": crop_names()}


@router.get("/soils")
def list_soils() -> dict:
    return {"soils": SOIL_TYPES}


@router.get("/weather-files")
def list_weather_files() -> dict:
    return {"weather_files": weather_files()}


@router.get("/co2-scenarios")
def list_co2_scenarios() -> dict:
    return {"co2_scenarios": CO2_SCENARIOS}
