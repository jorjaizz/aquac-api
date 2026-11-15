"""Tests for rotation preset loading and endpoints."""
from __future__ import annotations

import os

os.environ.setdefault("DEVELOPMENT", "True")

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services import presets

client = TestClient(app)

EXPECTED_SLUGS = {"maiz-trigo-soya", "maiz-monocultivo", "maiz-frijol"}


@pytest.fixture(autouse=True)
def _no_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_KEY",
        "ADMIN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_definitions_are_valid() -> None:
    definitions = presets.load_definitions()
    assert {entry["slug"] for entry in definitions} == EXPECTED_SLUGS


def test_expand_seasons_is_chronological() -> None:
    definition = presets.get_local_definition("maiz-trigo-soya")
    seasons = presets.expand_seasons(definition)
    assert len(seasons) == 20
    assert [season["crop"]["name"] for season in seasons[:4]] == [
        "Maize",
        "Wheat",
        "Soybean",
        "Maize",
    ]
    assert seasons[0]["sim_start_time"] == "2004/05/01"
    assert seasons[1]["sim_start_time"] == "2005/05/01"


def test_build_rotation_request_uses_custom_soil() -> None:
    definition = presets.get_local_definition("maiz-monocultivo")
    request = presets.build_rotation_request(definition)
    assert request.soil.soil_type == "custom"
    assert request.weather.type == "builtin"
    assert request.weather.name == "jocotenango_climate.txt"
    assert len(request.seasons) == 20
    assert request.irrigation.method == 0


def test_list_presets_falls_back_to_local() -> None:
    response = client.get("/presets")
    assert response.status_code == 200
    body = response.json()
    assert {entry["slug"] for entry in body["presets"]} == EXPECTED_SLUGS
    assert all("computed" in entry for entry in body["presets"])


def test_unknown_preset_returns_404() -> None:
    response = client.get("/presets/does-not-exist")
    assert response.status_code == 404


def test_preset_detail_returns_definition() -> None:
    response = client.get("/presets/maiz-monocultivo")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "maiz-monocultivo"
    assert body["source"] == "local"
    assert body["definition"]["cycle"][0]["crop"]["name"] == "Maize"


def test_recompute_is_disabled_without_admin_token() -> None:
    response = client.post("/presets/maiz-monocultivo/recompute")
    assert response.status_code == 403


def test_recompute_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected")
    response = client.post(
        "/presets/maiz-monocultivo/recompute",
        headers={"X-Admin-Token": "wrong"},
    )
    assert response.status_code == 401


def test_local_result_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(presets, "RESULTS_DIR", tmp_path)
    payload = presets.save_local_result(
        "demo", {"success": True, "summary": {}}, years=20, computed_at="2026-01-01T00:00:00Z"
    )
    assert payload["years"] == 20
    loaded = presets.read_local_result("demo")
    assert loaded is not None
    assert loaded["result"]["success"] is True
