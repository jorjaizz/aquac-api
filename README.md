# voidharvest-api

FastAPI wrapper around [AquaCrop-OSPy](https://github.com/aquacropos/aquacrop) for
the VoidHarvest / NASA Space Apps project. It exposes crop-water simulations and
precomputed crop-rotation presets stored in Supabase.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check used by Render |
| GET | `/catalog/crops` | Built-in crop names |
| GET | `/catalog/soils` | Built-in soil names |
| GET | `/catalog/weather-files` | Bundled climate files |
| GET | `/catalog/co2-scenarios` | Supported CO2 scenarios |
| POST | `/simulate` | Run one season |
| POST | `/simulate/rotation` | Run several seasons carrying soil water |
| POST | `/simulate/planting-dates` | Compare candidate planting dates |
| GET | `/presets` | List rotation presets |
| GET | `/presets/{slug}` | Preset definition plus precomputed result |
| POST | `/presets/{slug}/recompute` | Recompute a preset (admin token) |

Interactive docs: `/docs`.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-api.txt
Copy-Item .env.example .env   # fill in Supabase values
uvicorn api.main:app --reload
```

Run tests:

```powershell
pytest tests/api
```

The API works without Supabase: presets fall back to `data/rotations.json` and
`data/preset_results/*.json`.

## Supabase

1. Create the tables by running `supabase/schema.sql` in the Supabase SQL editor.
2. Set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in `.env` / Render.
3. Seed the definitions and precompute the results:

```powershell
python scripts/seed_presets.py
python scripts/precompute_rotations.py --all --push
```

The secret key is server-side only. Row Level Security is enabled with no public
policies, so the tables cannot be read with the publishable key.

## Presets

Rotation definitions live in `data/rotations.json`. Each definition declares a
crop cycle, a start year, the number of seasons, the bundled weather file and
the soil file under `aquacrop/data`.

To change the rotations, edit that file and rerun the two scripts above. The
precomputed results are written to `data/preset_results` and, when configured,
upserted into Supabase.

## Deployment (Render)

- Runtime: Docker
- Branch: `main`
- Health check path: `/health`
- Environment variables:
  - `SUPABASE_URL`
  - `SUPABASE_SECRET_KEY`
  - `ADMIN_TOKEN` (optional)
  - `CORS_ORIGINS` (for example `https://your-app.example.com`)
- Plan: Free works, but the first request after idling can take a minute.
  Presets return precomputed results, so the demo avoids running the model.

`render.yaml` describes the same service if you prefer a Blueprint.

## Data and attribution

- Model: AquaCrop-OSPy 3.1.0, Apache 2.0. See `LICENSE`.
- Weather: NASA POWER daily data for the demo site.
- Soil: ISRIC SoilGrids 2.0 with Saxton-Rawls pedotransfer functions.
