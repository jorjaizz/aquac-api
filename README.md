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
python scripts/precompute_rotations.py --all
```

The secret key is server-side only. Row Level Security is enabled with no public
policies, so the tables cannot be read with the publishable key.

## Presets and data flow

Supabase stores two different things: `rotations` holds each preset's input
definition (crop parameters, planting calendar, weather and soil references),
and `rotation_results` holds the AquaCrop output. Daily weather and soil files
remain bundled with the API under `aquacrop/data`; the database stores their
references, not copies of those files.

`data/rotations.json` is the checked-in fallback and the source used by the
seed/precompute scripts. `GET /presets` and `GET /presets/{slug}` return saved
results (Supabase first, local JSON fallback). To run the model using the input
definition currently stored in Supabase, call the admin-only
`POST /presets/{slug}/simulate` with `X-Admin-Token`. It runs the 20 seasons,
updates `rotation_results`, and returns the result. `POST /presets/{slug}/recompute`
remains an alias for the same operation. The token
must stay on a trusted server and must never be sent from browser code.

For VoidHarvest's normal display flow, the frontend should call the GET preset
endpoint and render its saved result. Recalculation is an administrative action;
it should not run every time a user opens the page.

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


## 20-year crop presets and estimate limits

The presets use the bundled Jocotenango daily climate series for 2004–2023 and the bundled SoilGrids-derived soil profile. Each preset runs one crop season per calendar year with a full-year soil-water balance. Maize uses AquaCrop's built-in Maize parameters.

Avocado and lemon are explicitly labeled annualized mature-orchard proxies. They reuse AquaCrop's built-in Maize phenology and water-stress response, with crop-specific water productivity, harvest index, and fresh-matter settings benchmark-adjusted to Guatemala's 2019–2023 national yield estimates published by MAGA/FAO. These are model-based approximations, not a perennial-tree lifecycle simulation or a local field calibration. The APIs expose both mean dry and fresh yield; for fruit comparisons, inspect fresh yield and the preset's `simulation_method` metadata.
