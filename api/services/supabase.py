"""Minimal PostgREST client for Supabase.

Only the operations needed by the presets layer are implemented: select and
upsert. Requests use the server-side secret key, which bypasses RLS, so this
module must never run in a browser.
"""
from __future__ import annotations

from typing import Any

import httpx

from api.settings import get_settings

DEFAULT_TIMEOUT_SECONDS = 15.0


class SupabaseError(RuntimeError):
    """Raised when Supabase is not configured or a request fails."""


def is_configured() -> bool:
    return get_settings().supabase_enabled


def _rest_url(table: str) -> str:
    settings = get_settings()
    if not settings.supabase_url:
        raise SupabaseError("SUPABASE_URL is not configured")
    base = settings.supabase_url.rstrip("/")
    if base.endswith("/rest/v1"):
        base = base[: -len("/rest/v1")]
    return f"{base}/rest/v1/{table}"


def _headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.supabase_key:
        raise SupabaseError("SUPABASE_SECRET_KEY is not configured")
    return {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    table: str,
    *,
    params: dict[str, str] | None = None,
    payload: Any = None,
    prefer: str | None = None,
) -> httpx.Response:
    headers = _headers()
    if prefer:
        headers["Prefer"] = prefer
    try:
        response = httpx.request(
            method,
            _rest_url(table),
            params=params,
            json=payload,
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise SupabaseError(f"Supabase request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise SupabaseError(
            f"Supabase returned {response.status_code} for {table}: {detail}"
        )
    return response


def select(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    response = _request("GET", table, params=params)
    if not response.content:
        return []
    data = response.json()
    return data if isinstance(data, list) else [data]


def upsert(
    table: str,
    rows: list[dict[str, Any]] | dict[str, Any],
    *,
    on_conflict: str | None = None,
) -> list[dict[str, Any]]:
    params = {"on_conflict": on_conflict} if on_conflict else None
    response = _request(
        "POST",
        table,
        params=params,
        payload=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if not response.content:
        return []
    data = response.json()
    return data if isinstance(data, list) else [data]
