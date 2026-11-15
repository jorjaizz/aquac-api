"""Small catalogs shared by the API routers."""
from __future__ import annotations

import os

SOIL_TYPES = [
    "Clay",
    "ClayLoam",
    "Default",
    "Loam",
    "LoamySand",
    "Sand",
    "SandyClay",
    "SandyClayLoam",
    "SandyLoam",
    "Silt",
    "SiltClay",
    "SiltClayLoam",
    "SiltLoam",
    "Paddy",
    "ac_TunisLocal",
    "custom",
]

CO2_SCENARIOS = [
    "ssp119",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp434",
    "ssp460",
    "ssp534os",
    "ssp585",
]


def crop_names() -> list[str]:
    from aquacrop.entities.crops.crop_params import crop_params

    return sorted(crop_params.keys())


def weather_files() -> list[str]:
    from aquacrop.utils.data import list_data

    return sorted(name for name in list_data() if name.endswith(".txt"))


def safe_weather_path(name: str) -> str:
    """Resolve a bundled weather file, rejecting path traversal."""
    from aquacrop.utils.data import get_filepath, list_data

    if os.path.basename(name) != name:
        raise ValueError("weather file name cannot contain directories")
    if name not in list_data():
        raise ValueError(f"unknown bundled weather file: {name}")
    return get_filepath(name)
