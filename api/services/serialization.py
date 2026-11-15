"""Helpers to turn pandas/numpy outputs into strict JSON friendly values."""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd


def clean_value(value: Any) -> Any:
    """Convert numpy/pandas scalars and missing values to plain JSON values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if (math.isnan(number) or math.isinf(number)) else number
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.ndarray):
        return [clean_value(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {key: clean_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_value(item) for item in value]
    return value


def dataframe_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return a list of JSON-safe records from a DataFrame."""
    records = frame.to_dict(orient="records")
    return [{str(key): clean_value(value) for key, value in row.items()} for row in records]
