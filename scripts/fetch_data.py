"""Fetch the inputs AquaCrop-OSPy needs for a site.

Weather comes from NASA POWER (daily point API) and soil texture/organic
carbon from ISRIC SoilGrids. The script writes:

* ``<name>_climate.txt``  AquaCrop weather file (Day Month Year ...)
* ``<name>_climate.json`` same data as JSON records
* ``<name>_soil.json``    custom soil profile consumable by the API
* the raw SoilGrids payload for traceability

Example::

    python scripts/fetch_data.py --lat 14.578 --lon -90.800 \
        --start 2004-01-01 --end 2023-12-31 --name jocotenango

Requires network access. The output can be used by the API either as a
bundled weather file (``"weather": {"type": "builtin", "name":
"jocotenango_climate.txt"}``) or pasted as inline records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
POWER_PARAMETERS = [
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "ALLSKY_SFC_SW_DWN",
    "WS2M",
    "RH2M",
]
POWER_FILL = -999.0

STANDARD_DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]
DEPTH_THICKNESS = [0.05, 0.10, 0.15, 0.30, 0.40, 1.00]


def _http_json(url: str, timeout: float = 120.0) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "aquacrop-ospy-api/0.1 (+https://github.com/aquacropos/aquacrop)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"HTTP {exc.code} from {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error contacting {url}: {exc.reason}") from exc


def _saturation_vapour_pressure(temp_c: float) -> float:
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def _extraterrestrial_radiation(latitude_deg: float, day_of_year: int) -> float:
    phi = math.radians(latitude_deg)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi / 365.0 * day_of_year)
    solar_declination = 0.409 * math.sin(2.0 * math.pi / 365.0 * day_of_year - 1.39)
    arg = -math.tan(phi) * math.tan(solar_declination)
    arg = max(-1.0, min(1.0, arg))
    sunset_hour_angle = math.acos(arg)
    return (
        (24.0 * 60.0 / math.pi)
        * 0.0820
        * dr
        * (
            sunset_hour_angle * math.sin(phi) * math.sin(solar_declination)
            + math.cos(phi) * math.cos(solar_declination) * math.sin(sunset_hour_angle)
        )
    )


def compute_et0(
    tmin: float,
    tmax: float,
    solar_radiation: float,
    wind_speed: float,
    relative_humidity: float,
    latitude: float,
    day_of_year: int,
    elevation: float,
) -> float:
    """FAO-56 Penman-Monteith daily reference evapotranspiration (mm/day)."""
    tmean = (tmax + tmin) / 2.0
    es_tmax = _saturation_vapour_pressure(tmax)
    es_tmin = _saturation_vapour_pressure(tmin)
    es = (es_tmax + es_tmin) / 2.0
    ea = es * max(0.0, min(100.0, relative_humidity)) / 100.0

    delta = 4098.0 * _saturation_vapour_pressure(tmean) / ((tmean + 237.3) ** 2)
    pressure = 101.3 * (((293.0 - 0.0065 * elevation) / 293.0) ** 5.26)
    gamma = 0.000665 * pressure

    ra = _extraterrestrial_radiation(latitude, day_of_year)
    rso = max(0.0, (0.75 + 2e-5 * elevation) * ra)
    rns = (1.0 - 0.23) * solar_radiation
    ratio = min(1.0, solar_radiation / rso) if rso > 0 else 1.0
    rnl = (
        4.903e-9
        * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0)
        * (0.34 - 0.14 * math.sqrt(max(ea, 0.0)))
        * (1.35 * ratio - 0.35)
    )
    rn = rns - rnl
    u2 = max(wind_speed, 0.1)

    numerator = 0.408 * delta * rn + gamma * (900.0 / (tmean + 273.0)) * u2 * (es - ea)
    denominator = delta + gamma * (1.0 + 0.34 * u2)
    et0 = numerator / denominator if denominator else 0.0
    return max(0.1, round(et0, 2))


def fetch_power_weather(
    latitude: float,
    longitude: float,
    start: dt.date,
    end: dt.date,
    elevation: float,
    timeout: float,
) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "parameters": ",".join(POWER_PARAMETERS),
            "community": "AG",
            "longitude": longitude,
            "latitude": latitude,
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }
    )
    payload = _http_json(f"{POWER_URL}?{query}", timeout=timeout)
    parameters = payload["properties"]["parameter"]
    dates = sorted(parameters["T2M_MAX"].keys())

    records: list[dict] = []
    for key in dates:
        values = {name: parameters[name].get(key, POWER_FILL) for name in POWER_PARAMETERS}
        if any(value == POWER_FILL for value in values.values()):
            continue
        day = dt.datetime.strptime(key, "%Y%m%d").date()
        tmin = float(values["T2M_MIN"])
        tmax = float(values["T2M_MAX"])
        solar = max(0.0, float(values["ALLSKY_SFC_SW_DWN"]))
        wind = float(values["WS2M"])
        humidity = float(values["RH2M"])
        et0 = compute_et0(
            tmin=tmin,
            tmax=tmax,
            solar_radiation=solar,
            wind_speed=wind,
            relative_humidity=humidity,
            latitude=latitude,
            day_of_year=day.timetuple().tm_yday,
            elevation=elevation,
        )
        records.append(
            {
                "date": day.isoformat(),
                "min_temp": round(tmin, 2),
                "max_temp": round(tmax, 2),
                "precipitation": round(float(values["PRECTOTCORR"]), 2),
                "solar_radiation_mj_m2_day": round(solar, 2),
                "wind_speed_m_s": round(wind, 2),
                "relative_humidity_pct": round(humidity, 2),
                "reference_et": et0,
            }
        )

    if not records:
        raise SystemExit("NASA POWER returned no usable records for the requested period")
    return records


def _soilgrids_depths(payload: dict) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    for layer in payload.get("properties", {}).get("layers", []):
        name = layer.get("name")
        if not name:
            continue
        values[name] = {}
        for depth in layer.get("depths", []):
            label = depth.get("label")
            mean = (depth.get("values") or {}).get("mean")
            if label is not None and mean is not None:
                values[name][label] = float(mean)
    return values


def fetch_soilgrids(latitude: float, longitude: float, timeout: float) -> dict:
    query = urllib.parse.urlencode(
        [
            ("lon", longitude),
            ("lat", latitude),
            ("property", "sand"),
            ("property", "clay"),
            ("property", "soc"),
            *[("depth", label) for label in STANDARD_DEPTHS],
            ("value", "mean"),
        ]
    )
    return _http_json(f"{SOILGRIDS_URL}?{query}", timeout=timeout)


def build_soil_layers(
    soilgrids_payload: dict,
    max_depth: float = 2.0,
) -> tuple[list[dict], list[float], list[dict]]:
    """Build custom soil layers from SoilGrids texture using Saxton-Rawls."""
    from aquacrop.entities.soil import Soil

    values = _soilgrids_depths(soilgrids_payload)
    missing = [name for name in ("sand", "clay", "soc") if name not in values]
    if missing:
        raise SystemExit(f"SoilGrids response is missing properties: {missing}")

    # 0.05 m compartments so every standard SoilGrids interval is representable.
    dz = [0.05] * max(1, int(round(max_depth / 0.05)))
    soil = Soil(soil_type="custom", dz=dz)
    layer_meta: list[dict] = []
    remaining = max_depth

    for label, thickness in zip(STANDARD_DEPTHS, DEPTH_THICKNESS):
        usable = min(thickness, remaining)
        if usable <= 0:
            break
        sand_pct = values["sand"].get(label, 0.0) / 10.0
        clay_pct = values["clay"].get(label, 0.0) / 10.0
        # SoilGrids soc is dg/kg; OM (%) ~= soc (dg/kg) * 0.01724
        organic_matter_pct = max(0.05, values["soc"].get(label, 0.0) * 0.01724)
        soil.add_layer_from_texture(usable, sand_pct, clay_pct, organic_matter_pct, 100)
        layer_meta.append(
            {
                "label": label,
                "thickness": round(usable, 3),
                "sand_pct": round(sand_pct, 2),
                "clay_pct": round(clay_pct, 2),
                "organic_matter_pct": round(organic_matter_pct, 3),
            }
        )
        remaining -= usable
        if remaining <= 0:
            break

    profile = soil.profile
    layers: list[dict] = []
    for layer_id in sorted(profile["Layer"].dropna().unique()):
        subset = profile[profile["Layer"] == layer_id]
        layers.append(
            {
                "thickness": round(float(subset["dz"].sum()), 3),
                "th_wp": round(float(subset["th_wp"].iloc[0]), 4),
                "th_fc": round(float(subset["th_fc"].iloc[0]), 4),
                "th_s": round(float(subset["th_s"].iloc[0]), 4),
                "ksat": round(float(subset["Ksat"].iloc[0]), 3),
                "penetrability": 100.0,
            }
        )
    return layers, dz, layer_meta


def write_weather_files(records: list[dict], out_dir: Path, name: str) -> tuple[Path, Path]:
    txt_path = out_dir / f"{name}_climate.txt"
    json_path = out_dir / f"{name}_climate.json"
    with txt_path.open("w", encoding="utf-8") as handle:
        handle.write("Day Month Year MinTemp MaxTemp Precipitation ReferenceET\n")
        for record in records:
            day = dt.date.fromisoformat(record["date"])
            handle.write(
                f"{day.day} {day.month} {day.year} "
                f"{record['min_temp']} {record['max_temp']} "
                f"{record['precipitation']} {record['reference_et']}\n"
            )
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return txt_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True, help="Latitude (decimal degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (decimal degrees)")
    parser.add_argument("--start", default="2004-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2023-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--name", default="site", help="Base name for output files")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aquacrop", "data"),
        help="Output directory (default: aquacrop/data so the API can load it as a builtin file)",
    )
    parser.add_argument("--elevation", type=float, default=0.0, help="Site elevation for ET0 (m)")
    parser.add_argument("--max-depth", type=float, default=2.0, help="Maximum soil profile depth (m)")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout (s)")
    parser.add_argument("--skip-weather", action="store_true")
    parser.add_argument("--skip-soil", action="store_true")
    args = parser.parse_args(argv)

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be on or after --start")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_weather:
        print(f"Fetching NASA POWER weather for ({args.lat}, {args.lon}) {start}..{end}")
        records = fetch_power_weather(args.lat, args.lon, start, end, args.elevation, args.timeout)
        txt_path, json_path = write_weather_files(records, out_dir, args.name)
        print(f"  {len(records)} daily records -> {txt_path.name}, {json_path.name}")

    soil_payload = None
    if not args.skip_soil:
        print(f"Fetching ISRIC SoilGrids for ({args.lat}, {args.lon})")
        soil_payload = fetch_soilgrids(args.lat, args.lon, args.timeout)
        layers, dz, layer_meta = build_soil_layers(soil_payload, args.max_depth)
        soil_document = {
            "soil": {
                "soil_type": "custom",
                "dz": dz,
                "layers": layers,
                "parameters": {"cn": 61, "rew": 9},
            },
            "metadata": {
                "source": "ISRIC SoilGrids v2.0",
                "latitude": args.lat,
                "longitude": args.lon,
                "max_depth_m": args.max_depth,
                "assumptions": {
                    "sand_clay": "SoilGrids g/kg converted to percent by dividing by 10",
                    "organic_matter": "soc (dg/kg) * 0.01724 -> organic matter percent",
                },
                "layers_source": layer_meta,
            },
        }
        soil_path = out_dir / f"{args.name}_soil.json"
        soil_path.write_text(json.dumps(soil_document, indent=2), encoding="utf-8")
        (out_dir / f"{args.name}_soilgrids_raw.json").write_text(
            json.dumps(soil_payload, indent=2), encoding="utf-8"
        )
        print(f"  {len(layers)} soil layers -> {soil_path.name}")

    print("Done. Use the weather file name with:")
    print(f'  {{"weather": {{"type": "builtin", "name": "{args.name}_climate.txt"}}}}')
    print(f"and the soil profile from {args.name}_soil.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
