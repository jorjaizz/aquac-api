"""Offline tests for the data acquisition helpers."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aquacrop.utils import prepare_weather
from scripts.fetch_data import (
    STANDARD_DEPTHS,
    build_soil_layers,
    compute_et0,
    write_weather_files,
)


def _soilgrids_payload() -> dict:
    return {
        "properties": {
            "layers": [
                {
                    "name": name,
                    "depths": [
                        {"label": label, "values": {"mean": mean}}
                        for label in STANDARD_DEPTHS
                    ],
                }
                for name, mean in (("sand", 400.0), ("clay", 200.0), ("soc", 80.0))
            ]
        }
    }


def test_compute_et0_returns_positive_value() -> None:
    et0 = compute_et0(
        tmin=12.0,
        tmax=26.0,
        solar_radiation=20.0,
        wind_speed=2.0,
        relative_humidity=65.0,
        latitude=14.578,
        day_of_year=120,
        elevation=1500.0,
    )
    assert 1.0 < et0 < 12.0


def test_build_soil_layers_respects_max_depth() -> None:
    layers, dz, meta = build_soil_layers(_soilgrids_payload(), max_depth=1.0)
    assert abs(sum(layer["thickness"] for layer in layers) - 1.0) < 1e-6
    assert len(dz) == 20
    assert len(meta) == len(layers)
    for layer in layers:
        assert 0 < layer["th_wp"] <= layer["th_fc"] <= layer["th_s"] < 1


def test_build_soil_layers_full_profile() -> None:
    layers, _, _ = build_soil_layers(_soilgrids_payload(), max_depth=2.0)
    assert len(layers) == 6
    assert abs(sum(layer["thickness"] for layer in layers) - 2.0) < 1e-6


def test_write_weather_files_roundtrips(tmp_path: Path) -> None:
    records = [
        {
            "date": "2000-01-01",
            "min_temp": 10.0,
            "max_temp": 20.0,
            "precipitation": 0.0,
            "reference_et": 3.5,
        },
        {
            "date": "2000-01-02",
            "min_temp": 11.0,
            "max_temp": 21.0,
            "precipitation": 2.0,
            "reference_et": 3.0,
        },
    ]
    txt_path, json_path = write_weather_files(records, tmp_path, "demo")
    assert txt_path.exists() and json_path.exists()

    frame = prepare_weather(str(txt_path))
    assert len(frame) == 2
    assert frame.iloc[0]["Date"].date() == dt.date(2000, 1, 1)
    assert frame.iloc[0]["ReferenceET"] == 3.5
