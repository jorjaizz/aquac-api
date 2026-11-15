"""Rotation presets backed by Supabase with a local JSON fallback."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aquacrop

from api.schemas import RotationRequest
from api.services import supabase

ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_PATH = ROOT / "data" / "rotations.json"
RESULTS_DIR = ROOT / "data" / "preset_results"
MODEL_VERSION = getattr(aquacrop, "__version__", "3.1.0")


class PresetError(RuntimeError):
    """Raised when a preset definition or result is invalid."""


class PresetNotFound(PresetError):
    """Raised when the requested preset does not exist."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PresetError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PresetError(f"invalid JSON in {path}: {exc}") from exc


def load_definitions() -> list[dict[str, Any]]:
    payload = _read_json(DEFINITIONS_PATH)
    if not isinstance(payload, list) or not payload:
        raise PresetError("data/rotations.json must contain a non-empty list")
    for entry in payload:
        _validate_definition(entry)
    return payload


def _validate_definition(definition: dict[str, Any]) -> None:
    if not isinstance(definition, dict):
        raise PresetError("every rotation definition must be an object")
    for key in ("slug", "name", "weather", "soil_file"):
        if not definition.get(key):
            raise PresetError(f"rotation definition is missing '{key}'")
    if definition.get("status") == "pending_model":
        if definition.get("simulation_supported") is not False:
            raise PresetError("pending_model presets must not claim simulation support")
        return
    if not isinstance(definition.get("cycle"), list) or not definition["cycle"]:
        raise PresetError("rotation 'cycle' must be a non-empty list")
    seasons = int(definition.get("seasons", 20))
    if seasons <= 0:
        raise PresetError("rotation 'seasons' must be positive")
    for item in definition["cycle"]:
        if not item.get("crop") or not item.get("sim_start") or not item.get("sim_end"):
            raise PresetError("every cycle item needs crop, sim_start and sim_end")

def get_local_definition(slug: str) -> dict[str, Any]:
    for definition in load_definitions():
        if definition["slug"] == slug:
            return definition
    raise PresetNotFound(f"unknown preset: {slug}")


def _aquacrop_data_dir() -> Path:
    return Path(aquacrop.__file__).resolve().parent / "data"


def load_soil_file(name: str) -> dict[str, Any]:
    if Path(name).name != name:
        raise PresetError("soil_file cannot contain directories")
    path = _aquacrop_data_dir() / name
    payload = _read_json(path)
    soil = payload.get("soil") if isinstance(payload, dict) else None
    if not isinstance(soil, dict):
        raise PresetError(f"{name} does not contain a 'soil' object")
    return soil


def _month_day(value: str) -> tuple[int, int]:
    try:
        month, day = value.split("/")
        return int(month), int(day)
    except (AttributeError, ValueError) as exc:
        raise PresetError(f"invalid month/day value: {value!r}") from exc


def expand_seasons(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the crop cycle into one season per year, in chronological order."""
    _validate_definition(definition)
    if definition.get("status") == "pending_model":
        raise PresetError(f"preset {definition['slug']} is pending a validated perennial-crop model")
    cycle = definition["cycle"]
    start_year = int(definition.get("start_year", 2004))
    seasons = int(definition.get("seasons", 20))

    expanded: list[dict[str, Any]] = []
    for index in range(seasons):
        item = cycle[index % len(cycle)]
        year = start_year + index
        end_year = year
        if _month_day(item["sim_end"]) < _month_day(item["sim_start"]):
            end_year += 1
        expanded.append(
            {
                "sim_start_time": f"{year}/{item['sim_start']}",
                "sim_end_time": f"{end_year}/{item['sim_end']}",
                "crop": dict(item["crop"]),
            }
        )
    return expanded


def build_rotation_request(definition: dict[str, Any]) -> RotationRequest:
    _validate_definition(definition)
    if definition.get("status") == "pending_model":
        raise PresetError(f"preset {definition['slug']} is pending a validated perennial-crop model")
    payload = {
        "weather": definition["weather"],
        "soil": load_soil_file(definition["soil_file"]),
        "seasons": expand_seasons(definition),
        "initial_water_content": definition.get(
            "initial_water_content", {"value": ["FC"]}
        ),
        "irrigation": definition.get("irrigation", {"method": 0}),
        "carry_water_between_seasons": bool(
            definition.get("carry_water_between_seasons", True)
        ),
    }
    return RotationRequest.model_validate(payload)


# ---------------------------------------------------------------------------
# Local results
# ---------------------------------------------------------------------------


def _result_path(slug: str) -> Path:
    if Path(slug).name != slug:
        raise PresetError("invalid preset slug")
    return RESULTS_DIR / f"{slug}.json"


def read_local_result(slug: str) -> dict[str, Any] | None:
    path = _result_path(slug)
    if not path.exists():
        return None
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else None


def save_local_result(
    slug: str,
    result: dict[str, Any],
    *,
    years: int,
    computed_at: str | None = None,
) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": slug,
        "years": years,
        "model_version": MODEL_VERSION,
        "computed_at": computed_at or _now_iso(),
        "result": result,
    }
    _result_path(slug).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------


def upsert_definition(definition: dict[str, Any]) -> dict[str, Any]:
    _validate_definition(definition)
    row = {
        "slug": definition["slug"],
        "name": definition["name"],
        "description": definition.get("description"),
        "definition": definition,
        "seasons": int(definition.get("seasons", 20)),
        "updated_at": _now_iso(),
    }
    rows = supabase.upsert("rotations", row, on_conflict="slug")
    return rows[0] if rows else row


def upsert_result(
    slug: str,
    result: dict[str, Any],
    *,
    years: int,
    computed_at: str | None = None,
) -> dict[str, Any]:
    row = {
        "slug": slug,
        "years": years,
        "model_version": MODEL_VERSION,
        "computed_at": computed_at or _now_iso(),
        "result": result,
    }
    rows = supabase.upsert("rotation_results", row, on_conflict="slug")
    return rows[0] if rows else row


def _select_definition(slug: str) -> dict[str, Any] | None:
    rows = supabase.select(
        "rotations",
        {"slug": f"eq.{slug}", "select": "slug,name,description,definition,seasons,updated_at"},
    )
    return rows[0] if rows else None


def _select_result(slug: str) -> dict[str, Any] | None:
    rows = supabase.select(
        "rotation_results",
        {
            "slug": f"eq.{slug}",
            "select": "slug,years,model_version,computed_at,result",
        },
    )
    return rows[0] if rows else None


def _summary(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {
            "computed": False,
            "computed_at": None,
            "mean_dry_yield_tonne_ha": None,
            "mean_fresh_yield_tonne_ha": None,
        }
    result = entry.get("result") or {}
    summary = result.get("summary") or {}
    computed = bool(result.get("success", True))
    return {
        "computed": computed,
        "computed_at": entry.get("computed_at") if computed else None,
        "mean_dry_yield_tonne_ha": summary.get("mean_dry_yield_tonne_ha") if computed else None,
        "mean_fresh_yield_tonne_ha": summary.get("mean_fresh_yield_tonne_ha") if computed else None,
    }

def _local_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    try:
        definitions = load_definitions()
    except PresetError:
        return index
    for definition in definitions:
        index[definition["slug"]] = read_local_result(definition["slug"]) or {}
    return index


def list_presets() -> list[dict[str, Any]]:
    # Repository definitions are canonical; Supabase stores computed results.
    definitions = load_definitions()
    results = _local_index()
    if supabase.is_configured():
        try:
            result_rows = supabase.select(
                "rotation_results",
                {"select": "slug,years,model_version,computed_at,result", "order": "slug.asc"},
            )
            results.update({row["slug"]: row for row in result_rows})
        except supabase.SupabaseError:
            pass

    presets = []
    for definition in definitions:
        slug = definition["slug"]
        entry = results.get(slug)
        if definition.get("status") == "pending_model":
            entry = None
        presets.append({
            "slug": slug,
            "name": definition["name"],
            "description": definition.get("description"),
            "seasons": definition.get("seasons", 0),
            "years": (entry or {}).get("years", definition.get("seasons", 0)),
            "updated_at": (entry or {}).get("updated_at"),
            **_summary(entry),
            "status": definition.get("status", "ready"),
        })
    return presets

def get_preset(slug: str) -> dict[str, Any]:
    # Use the checked-in definition so stale database rows cannot resurrect retired presets.
    definition = get_local_definition(slug)
    result_entry: dict[str, Any] | None = None
    source = "local"
    if definition.get("status") != "pending_model" and supabase.is_configured():
        try:
            result_entry = _select_result(slug)
            if result_entry:
                source = "supabase"
        except supabase.SupabaseError:
            result_entry = None
    if result_entry is None and definition.get("status") != "pending_model":
        result_entry = read_local_result(slug)

    return {
        "slug": slug,
        "name": definition.get("name"),
        "definition": definition,
        "source": source,
        "years": (result_entry or {}).get("years", definition.get("seasons", 0)),
        "model_version": (result_entry or {}).get("model_version"),
        "computed_at": (result_entry or {}).get("computed_at"),
        "computed": _summary(result_entry)["computed"],
        "result": (result_entry or {}).get("result"),
        **_summary(result_entry),
        "status": definition.get("status", "ready"),
    }

def precompute_preset(
    slug: str,
    *,
    push: bool = True,
    write_local: bool = True,
) -> dict[str, Any]:
    definition = get_local_definition(slug)
    years = int(definition.get("seasons", 0))
    computed_at = _now_iso()

    if definition.get("status") == "pending_model":
        result = {
            "success": False,
            "status": "pending_model",
            "message": "No yield is published until a perennial-crop model is parameterized and validated.",
            "summary": {"n_seasons": 0, "mean_dry_yield_tonne_ha": None},
        }
    else:
        from api.services.simulation import run_rotation
        request = build_rotation_request(definition)
        result = run_rotation(request)
        years = int(definition.get("seasons", len(request.seasons)))

    payload = {"slug": slug, "years": years, "model_version": MODEL_VERSION,
               "computed_at": computed_at, "result": result}
    if write_local:
        save_local_result(slug, result, years=years, computed_at=computed_at)

    stored_in_supabase = False
    supabase_error: str | None = None
    if push and supabase.is_configured():
        try:
            upsert_definition(definition)
            upsert_result(slug, result, years=years, computed_at=computed_at)
            stored_in_supabase = True
        except supabase.SupabaseError as exc:
            supabase_error = str(exc)

    return {**payload, "stored_locally": write_local,
            "stored_in_supabase": stored_in_supabase, "supabase_error": supabase_error}
