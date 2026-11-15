"""Run the rotation presets and store their results locally and in Supabase."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.services import supabase  # noqa: E402
from api.services.presets import (  # noqa: E402
    PresetError,
    load_definitions,
    precompute_preset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        action="append",
        dest="slugs",
        help="Preset slug to compute. Repeatable. Defaults to every preset.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compute every preset in data/rotations.json.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Do not write to Supabase (local JSON only).",
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Do not write data/preset_results/*.json.",
    )
    args = parser.parse_args()

    if args.slugs:
        slugs = args.slugs
    elif args.all:
        slugs = [entry["slug"] for entry in load_definitions()]
    else:
        slugs = [entry["slug"] for entry in load_definitions()]

    push = not args.no_push and supabase.is_configured()
    if not args.no_push and not push:
        print("Supabase is not configured; writing local results only.", file=sys.stderr)

    failed = False
    for slug in slugs:
        print(f"computing {slug} ...", flush=True)
        try:
            payload = precompute_preset(
                slug, push=push, write_local=not args.no_local
            )
        except PresetError as exc:
            print(f"  error: {exc}", file=sys.stderr)
            failed = True
            continue

        summary = payload["result"].get("summary", {})
        print(
            "  seasons={n} mean_yield={yield_} t/ha local={local} supabase={remote}".format(
                n=summary.get("n_seasons"),
                yield_=summary.get("mean_dry_yield_tonne_ha"),
                local=payload["stored_locally"],
                remote=payload["stored_in_supabase"],
            )
        )
        if payload.get("supabase_error"):
            print(f"  supabase: {payload['supabase_error']}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
