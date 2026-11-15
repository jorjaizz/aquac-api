"""Upsert the rotation definitions from data/rotations.json into Supabase."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.services import supabase  # noqa: E402
from api.services.presets import load_definitions, upsert_definition  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the definitions without writing to Supabase.",
    )
    args = parser.parse_args()

    definitions = load_definitions()
    if args.dry_run:
        for definition in definitions:
            print(f"{definition['slug']}: {definition['name']}")
        return 0

    if not supabase.is_configured():
        print("SUPABASE_URL and SUPABASE_SECRET_KEY are required.", file=sys.stderr)
        return 1

    try:
        for definition in definitions:
            upsert_definition(definition)
            print(f"upserted {definition['slug']}")
    except supabase.SupabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
