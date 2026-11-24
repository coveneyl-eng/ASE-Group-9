# Flood thin slice dashboard

A React dashboard and a small FastAPI backend for the team's thin slice in
[`flood-thin-slice/`](../flood-thin-slice). It reads what `load_all.py` puts into PostGIS and Kafka
and shows it on one page. It does not load data itself.

| Panel | Shows | Source |
|---|---|---|
| Flood check | Dublin Port level against the CFRAM 10% / 0.5% / 0.1% AEP thresholds, the active band, and assets graded safe / caution / unsafe | Same rules as `load_all.flood_check()`: `readings`, `cfram_nodes`, `flood_extent_coast`, `infrastructure`, `dsm`, `small_areas` |
| Map | The active coastal extent and the affected assets, coloured by grade | as above |
| Readings | 48 h Dublin Port chart and the latest level per station | `readings` |
| Kafka live feed | Every message on `flood.readings` as it arrives, plus a **Send through Kafka** box for what-if levels | Kafka topic `flood.readings` |
| System health | PostgreSQL, extensions (PostGIS, raster, TimescaleDB, pgRouting), Kafka, and row counts for all 15 tables `load_all.py` creates | `information_schema` + `count(*)` |

A what-if level is published in `load_all.publish_reading`'s format with `source: "simulated"`.
It goes through Kafka into the `readings` table like any other reading. The real-data views
(chart, latest level, default flood check) ignore simulated rows.

## Run it

### Option A: next to the existing compose (no Docker build)

```bash
# 1. the thin slice, as before
cd flood-thin-slice
docker compose up -d
python load_all.py              # loads PostGIS, publishes + consumes readings

# 2. the dashboard API (new terminal)
cd dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.app:app --port 8080

# 3. the React app (new terminal)
cd dashboard/web
npm install
npm run dev                     # http://localhost:5173
```

For a single port, run `npm run build` once. The API then serves the built app at
http://localhost:8080.

### Option B: everything in Docker

```bash
docker compose -f flood-thin-slice/docker-compose.yml \
               -f dashboard/docker-compose.dashboard.yml up -d --build
cd flood-thin-slice && python load_all.py
open http://localhost:8080
```

The override file does not change `flood-thin-slice/docker-compose.yml`. It gives Kafka a second,
internal listener so the dashboard container can reach it. `load_all.py` on your laptop still uses
`localhost:9092`.

## Configuration

The variables are the same ones `load_all.py` uses, so the same `.env` works for both.

| Variable | Default |
|---|---|
| `DB_URL` | `postgresql+psycopg://flood:flood@localhost:5432/flood` |
| `KAFKA` | `localhost:9092` |
| `KAFKA_TOPIC` | `flood.readings` |
| `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD` | unset (PLAINTEXT). Set these for Azure Event Hubs / Confluent Cloud. |
| `WEB_DIST` | `web/dist` |

On Azure, deploy the image from `Dockerfile` as one more container next to the ones
in `azure_deployment`. Set `DB_URL` and `KAFKA*` to the same values `load_all` uses there.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | components, layer row counts, live-feed stats (cached 5 s) |
| GET | `/api/readings` | latest per station + 48 h Dublin Port series |
| GET | `/api/flood?level=2.9` | flood check on the latest real reading, or a what-if level |
| POST | `/api/simulate` `{"level_m": 2.9}` | publish a simulated Dublin Port reading to Kafka |
| WS | `/api/live` | Kafka messages as they arrive (last 50 replayed on connect) |

## Tests

```bash
pip install pytest httpx
pytest -q                                   # rule tests always run
psql "$PG" -f tests/seed.sql                # seed a test DB to also run the API tests
KAFKA_TESTS=1 pytest -q                     # plus the simulate → Kafka → WebSocket round trip
```

`tests/seed.sql` is a small, made-up fixture with the same table shapes as `load_all.py` output.
It is for tests only and is not real data. CI (`.github/workflows/dashboard.yml`) runs everything
against PostGIS and Kafka service containers, then builds the web app and the Docker image.

## Layout

```
dashboard/
  api/app.py        FastAPI: health, readings, flood, simulate, /api/live WebSocket
  api/flood.py      load_all.flood_check() logic, returning JSON instead of printing
  web/src/          React + TypeScript + MapLibre (App, FloodPanel, FloodMap, ReadingsPanel, LivePanel, HealthPanel)
  tests/            rule tests, API tests, seed.sql
  Dockerfile        node build → python runtime on :8080
  docker-compose.dashboard.yml
```
