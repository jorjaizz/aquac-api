"""Smoke test the deployed or local API."""
from __future__ import annotations

import argparse
import sys

import httpx


def check(client: httpx.Client, path: str) -> dict:
    response = client.get(path)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {path} -> {response.status_code}: {response.text[:300]}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--skip-simulate",
        action="store_true",
        help="Skip the short /simulate request.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=args.timeout) as client:
        try:
            health = check(client, "/health")
            print(f"health: {health}")

            crops = check(client, "/catalog/crops")["crops"]
            print(f"crops: {len(crops)}")

            presets = check(client, "/presets")["presets"]
            print(f"presets: {len(presets)}")
            for preset in presets:
                print(
                    "  {slug}: computed={computed} yield={yield_}".format(
                        slug=preset["slug"],
                        computed=preset.get("computed"),
                        yield_=preset.get("mean_dry_yield_tonne_ha"),
                    )
                )

            if presets:
                detail = check(client, f"/presets/{presets[0]['slug']}")
                print(
                    "  detail {slug}: source={source} computed={computed}".format(
                        slug=detail["slug"],
                        source=detail["source"],
                        computed=detail["computed"],
                    )
                )

            if not args.skip_simulate:
                payload = {
                    "sim_start_time": "1979/10/01",
                    "sim_end_time": "1980/05/30",
                    "weather": {"type": "builtin", "name": "tunis_climate.txt"},
                    "soil": {"soil_type": "SandyLoam"},
                    "crop": {"name": "Wheat", "planting_date": "10/01"},
                    "initial_water_content": {"value": ["FC"]},
                }
                response = client.post("/simulate", json=payload)
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"POST /simulate -> {response.status_code}: {response.text[:300]}"
                    )
                body = response.json()
                print(f"simulate: yield={body['final_stats'][0]['Dry yield (tonne/ha)']}")
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            print(f"smoke test failed: {exc}", file=sys.stderr)
            return 1

    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
