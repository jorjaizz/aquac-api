"""Weather input handling for the API."""
from __future__ import annotations

import os

import pandas as pd

from aquacrop.utils import prepare_weather

from api.constants import safe_weather_path
from api.schemas import BuiltinWeather, InlineWeather, WeatherInput

# AquaCrop reads the weather row positionally as
# [MinTemp, MaxTemp, Precipitation, ReferenceET, Date], so the order matters.
_COLUMNS = ["MinTemp", "MaxTemp", "Precipitation", "ReferenceET", "Date"]


class WeatherError(ValueError):
    """Raised when the supplied weather series cannot be used by AquaCrop."""


def _from_builtin(source: BuiltinWeather) -> pd.DataFrame:
    try:
        path = safe_weather_path(source.name)
    except ValueError as exc:
        raise WeatherError(str(exc)) from exc
    if not os.path.exists(path):
        raise WeatherError(f"weather file not found: {source.name}")
    frame = prepare_weather(path)
    return frame[_COLUMNS]


def _from_inline(source: InlineWeather) -> pd.DataFrame:
    rows = [
        {
            "MinTemp": float(record.min_temp),
            "MaxTemp": float(record.max_temp),
            "Precipitation": float(record.precipitation),
            "ReferenceET": float(record.reference_et),
            "Date": pd.Timestamp(record.date),
        }
        for record in source.records
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise WeatherError("weather series is empty")

    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"])

    duplicated = frame["Date"].duplicated()
    if duplicated.any():
        first = frame.loc[duplicated, "Date"].iloc[0]
        raise WeatherError(f"duplicate weather date: {first.date().isoformat()}")

    frame = frame.sort_values("Date").reset_index(drop=True)

    expected = pd.date_range(frame["Date"].iloc[0], frame["Date"].iloc[-1], freq="D")
    if len(expected) != len(frame) or not expected.equals(pd.DatetimeIndex(frame["Date"])):
        missing = expected.difference(pd.DatetimeIndex(frame["Date"]))
        example = missing[0].date().isoformat() if len(missing) else "unknown"
        raise WeatherError(
            "weather series must be daily and contiguous; "
            f"detected gaps or extra dates (first gap: {example})"
        )

    invalid_temperature = frame["MinTemp"] > frame["MaxTemp"]
    if invalid_temperature.any():
        row = frame.loc[invalid_temperature].iloc[0]
        raise WeatherError(
            "min_temp cannot be greater than max_temp on "
            f"{row['Date'].date().isoformat()}"
        )

    if (frame["Precipitation"] < 0).any():
        raise WeatherError("precipitation cannot be negative")

    frame["ReferenceET"] = frame["ReferenceET"].clip(lower=0.1)
    return frame[_COLUMNS].reset_index(drop=True)


def load_weather(source: WeatherInput) -> pd.DataFrame:
    """Build a validated AquaCrop weather DataFrame from an API payload."""
    if isinstance(source, BuiltinWeather):
        frame = _from_builtin(source)
    elif isinstance(source, InlineWeather):
        frame = _from_inline(source)
    else:  # pragma: no cover - guarded by pydantic
        raise WeatherError("unsupported weather source")
    return _validate(frame)
