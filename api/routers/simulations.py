"""Simulation endpoints backed by AquaCrop-OSPy."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import (
    PlantingDateRequest,
    PlantingDateResponse,
    RotationRequest,
    RotationResponse,
    SimulationRequest,
    SimulationResponse,
)
from api.services.simulation import (
    SimulationError,
    run_planting_dates,
    run_rotation,
    run_simulation,
)

router = APIRouter(prefix="/simulate", tags=["simulation"])


def _bad_request(exc: SimulationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("", response_model=SimulationResponse, summary="Run one AquaCrop simulation")
def simulate(request: SimulationRequest) -> dict:
    try:
        return run_simulation(request)
    except SimulationError as exc:
        raise _bad_request(exc) from exc


@router.post(
    "/rotation",
    response_model=RotationResponse,
    summary="Run a sequence of seasons, carrying soil water between them",
)
def simulate_rotation(request: RotationRequest) -> dict:
    try:
        return run_rotation(request)
    except SimulationError as exc:
        raise _bad_request(exc) from exc


@router.post(
    "/planting-dates",
    response_model=PlantingDateResponse,
    summary="Compare model outputs for several candidate planting dates",
)
def simulate_planting_dates(request: PlantingDateRequest) -> dict:
    try:
        return run_planting_dates(request)
    except SimulationError as exc:
        raise _bad_request(exc) from exc
