"""Integration tests for the FastAPI wrapper."""
from __future__ import annotations

import os

os.environ.setdefault("DEVELOPMENT", "True")

import pandas as pd
from fastapi.testclient import TestClient

from aquacrop.utils import get_filepath, prepare_weather
from api.main import app

client = TestClient(app)

BUILTIN_WEATHER = {"type": "builtin", "name": "tunis_climate.txt"}


def _inline_weather(start: str, end: str) -> list[dict]:
    frame = prepare_weather(get_filepath("tunis_climate.txt"))
    frame = frame[(frame["Date"] >= pd.Timestamp(start)) & (frame["Date"] <= pd.Timestamp(end))]
    return [
        {
            "date": row.Date.date().isoformat(),
            "min_temp": float(row.MinTemp),
            "max_temp": float(row.MaxTemp),
            "precipitation": float(row.Precipitation),
            "reference_et": float(row.ReferenceET),
        }
        for row in frame.itertuples()
    ]


def _wheat_crop(planting_date: str = "10/01") -> dict:
    return {"name": "Wheat", "planting_date": planting_date}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_contains_wheat_and_soils() -> None:
    crops = client.get("/catalog/crops").json()["crops"]
    soils = client.get("/catalog/soils").json()["soils"]
    weather_files = client.get("/catalog/weather-files").json()["weather_files"]
    assert "Wheat" in crops
    assert "SandyLoam" in soils
    assert "tunis_climate.txt" in weather_files


def test_simulate_with_builtin_weather() -> None:
    payload = {
        "sim_start_time": "1979/10/01",
        "sim_end_time": "1980/05/30",
        "weather": BUILTIN_WEATHER,
        "soil": {"soil_type": "SandyLoam"},
        "crop": _wheat_crop(),
        "initial_water_content": {"value": ["FC"]},
        "options": {"include_crop_growth": True},
    }
    response = client.post("/simulate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert len(body["final_stats"]) == 1
    assert round(body["final_stats"][0]["Dry yield (tonne/ha)"], 2) == 8.94
    assert body["crop_growth"]
    assert body["meta"]["n_weather_days"] == len(_inline_weather("1979/10/01", "1980/05/30"))


def test_simulate_with_inline_weather() -> None:
    payload = {
        "sim_start_time": "1979/10/01",
        "sim_end_time": "1980/05/30",
        "weather": {
            "type": "inline",
            "records": _inline_weather("1979/10/01", "1980/05/30"),
        },
        "soil": {"soil_type": "SandyLoam"},
        "crop": _wheat_crop(),
        "initial_water_content": {"value": ["FC"]},
    }
    response = client.post("/simulate", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


def test_simulate_rejects_weather_gaps() -> None:
    payload = {
        "sim_start_time": "2000/01/01",
        "sim_end_time": "2000/01/03",
        "weather": {
            "type": "inline",
            "records": [
                {
                    "date": "2000-01-01",
                    "min_temp": 10,
                    "max_temp": 20,
                    "precipitation": 0,
                    "reference_et": 3,
                },
                {
                    "date": "2000-01-03",
                    "min_temp": 10,
                    "max_temp": 20,
                    "precipitation": 0,
                    "reference_et": 3,
                },
            ],
        },
        "soil": {"soil_type": "SandyLoam"},
        "crop": _wheat_crop(),
        "initial_water_content": {"value": ["FC"]},
    }
    response = client.post("/simulate", json=payload)
    assert response.status_code == 400
    assert "contiguous" in response.json()["detail"]


def test_simulate_rejects_custom_soil_without_layers() -> None:
    payload = {
        "sim_start_time": "1979/10/01",
        "sim_end_time": "1980/05/30",
        "weather": BUILTIN_WEATHER,
        "soil": {"soil_type": "custom"},
        "crop": _wheat_crop(),
        "initial_water_content": {"value": ["FC"]},
    }
    response = client.post("/simulate", json=payload)
    assert response.status_code == 422


def test_rotation_carries_water_between_seasons() -> None:
    payload = {
        "weather": BUILTIN_WEATHER,
        "soil": {"soil_type": "SandyLoam"},
        "seasons": [
            {
                "sim_start_time": "1979/10/01",
                "sim_end_time": "1980/05/30",
                "crop": _wheat_crop(),
            },
            {
                "sim_start_time": "1980/10/01",
                "sim_end_time": "1981/05/30",
                "crop": _wheat_crop(),
            },
        ],
        "initial_water_content": {"value": ["FC"]},
    }
    response = client.post("/simulate/rotation", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert len(body["seasons"]) == 2
    assert body["summary"]["n_seasons"] == 2
    assert body["summary"]["mean_dry_yield_tonne_ha"] is not None


def test_planting_dates_returns_one_result_per_candidate() -> None:
    payload = {
        "sim_start_time": "1979/10/01",
        "sim_end_time": "1980/05/30",
        "weather": BUILTIN_WEATHER,
        "soil": {"soil_type": "SandyLoam"},
        "crop": _wheat_crop(),
        "candidate_planting_dates": ["10/01", "11/01"],
        "initial_water_content": {"value": ["FC"]},
    }
    response = client.post("/simulate/planting-dates", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 2
    assert [item["planting_date"] for item in body["results"]] == ["10/01", "11/01"]
