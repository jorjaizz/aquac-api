"""Runtime configuration read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_key: str | None
    admin_token: str | None

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


def get_settings() -> Settings:
    """Read settings on every call so tests can change the environment."""
    return Settings(
        supabase_url=_clean(os.getenv("SUPABASE_URL")),
        supabase_key=_clean(
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
        ),
        admin_token=_clean(os.getenv("ADMIN_TOKEN")),
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
