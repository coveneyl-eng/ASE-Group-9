# Smart City Coordinating Agents — Thin Slice (ASE Group 9)

Lives beside the team's API clients: every outside call goes through `../APIs` (opwAPI, marineTideAPI,
metEireannAPI, ticketmasterAPI, trafficCongestionAPI, busAPI, notification/SMSapi + Emailapi), and the
city's traffic lights are Oleksandr's `../APIs/trafficControlAPI.py` server. `../flood-thin-slice` is the
earlier hello-world loader for the real Dublin datasets; this folder wires all the technologies together.

The thin slice that verifies the **technical architecture**. It is not a feature demo. Every technology
named in the architecture is installed, and each pair that must interact is exercised. One simulated flood
reading travels the whole chain:

```
sensor sim ─MQTT/TLS 1.3─▶ Mosquitto ─▶ MQTT bridge ─▶ Kafka flood.readings
  ─▶ Flood Detector (CFRAM threshold, PostGIS) ─▶ flood.events
  ─▶ Flood Scope (PostGIS overlay + LiDAR DTM elevation, TimescaleDB impacts) ─▶ flood.impacts
       ├─▶ Rerouting (pgRouting avoids flooded edges) ─▶ traffic.reroute + lights at the flood held red
       ├─▶ Notification Agent (FastAPI) ─▶ SMS (SMSAPI) + email (Gmail API) via APIs/notification
       └─▶ WebSocket hub ─wss via NGINX─▶ Officials' portal (React + TS + MapLibre)
Official ─HTTPS─▶ NGINX (TLS, auth_request JWT) ─▶ Approval service (OAuth2/JWT, roles, Key Vault secret)
  ─▶ PostgreSQL audit log + Blob report + Kafka dispatch.approved ─▶ Notification Agent ─▶ responders
Ingest workers ─../APIs─▶ OPW / Met Éireann / Marine Institute / Ticketmaster / TomTom / NTA ─▶ Kafka
  ─▶ Flood Predicting Agent (scikit-learn) · Event Monitoring → Event Coordinating → Public Transport
  · Traffic Monitoring (TomTom) → Traffic Control → lights held green (trafficControlAPI)
Static loader: ogr2ogr (GDAL) + osm2pgsql → PostGIS; GeoPandas + rasterio DTM sampling; layers → Blob
All agents: OpenTelemetry metrics → Prometheus → Grafana dashboard
```

## Run it (Docker Desktop, ~5 min first build)

```bash
cd thin-slice
./scripts/gen_certs.sh            # local CA + certs for Mosquitto, NGINX, Kafka (needs openssl)
cp .env.example .env              # optional: add provider keys; leave empty for dry-run + fixtures
docker compose up -d --build
docker compose logs -f static-loader   # wait for "[loader] done"
./scripts/verify.sh               # end-to-end verifier + Postman/Newman suite, JUnit XML in reports/
```

| URL | What |
|---|---|
| https://localhost:8444 | Officials' portal: **System health** dashboard + Operations (sign in `dispatcher` / `dispatch-demo`) |
| https://localhost:8444/?public | Public status map (no login) |
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana → *Smart City thin slice* dashboard |
| http://localhost:8090/lights | Traffic-light API (see which lights the agents are holding) |

Trigger a flood by hand: `docker compose run --rm sensor-sim python -m smartcity.simulators.sensors --flood`

## System-health dashboard

The portal opens on **System health**: one screen that shows every technology is up and talking.

- **Components**: a probe per technology (Mosquitto, Kafka, PostgreSQL and extensions, static layers, Blob Storage,
  Key Vault, every agent, Notification, Approval, WebSocket hub, NGINX, traffic-light API, Prometheus, Grafana),
  re-run every 3 s. Green = healthy, amber = degraded, red = down, hollow = not deployed in this environment.
- **Live flood pipeline**: follows one reading by its trace id through MQTT, Kafka, the flood agents, rerouting and
  the SMS/email alerts, with the time each stage took.
- **Test flood reading**: emergency responders can publish a reading through Mosquitto from the page.
- **Kafka topics** and **sensor-to-alert latency** (p95 over the last hour against the 5 s target).

Backend: `GET /api/hub/status` and `POST /api/hub/simulate-flood` on the WebSocket hub (`services/ws_hub.py`,
probes in `services/health.py`); both need a JWT, and the trigger needs the `emergency_responder` role.

## Demo script (≈5 minutes)

1. `docker compose ps`: every container in the technical architecture is up.
2. Open the portal and sign in: the System health dashboard shows every component green.
3. Press **Send reading** on the dashboard and watch the pipeline light up stage by stage, then run
   `./scripts/verify.sh` for the full PASS/FAIL table. The Operations tab shows the flood extent and the
   assets graded red, amber or green.
4. Walk through the PASS table: one line per technology interaction. Point out the
   **sensor→alert latency** (≈1 s against the 5 s QoS target) and the **planner 403 / dispatcher 200**
   role check.
5. Click **Approve responder dispatch**. Show the confirmation dialog, then the audit row:
   `docker compose exec postgres psql -U smartcity -c "select * from audit_log order by id desc limit 1"`.
6. Grafana: latency p95 and decisions per agent.
7. Resilience: `docker compose restart notification`, then trigger a flood. No alert is lost, and the
   consumer resumes from its committed Kafka offset.

## Technology → evidence

| Architecture technology | Where | Verified by |
|---|---|---|
| Python 3, Pydantic topic models | `smartcity/models.py` | every check |
| Eclipse Mosquitto, MQTT over TLS 1.3, QoS 1 | `deploy/mosquitto` | *Sensor simulator → Mosquitto* |
| Sensor simulators (water, drains) | `smartcity/simulators/sensors.py` | same |
| MQTT → Kafka bridge | `smartcity/services/mqtt_bridge.py` | *MQTT bridge → Kafka* |
| Apache Kafka, SASL over TLS, topic per domain | `docker-compose.yml`, `smartcity/bus.py` | *Kafka event bus* + every agent hop |
| Ingest workers via `../APIs`: OPW, Met Éireann, Marine Institute, Ticketmaster, TomTom, NTA | `smartcity/services/ingest.py`, `smartcity/team_apis.py` | *Ingest via team APIs/* |
| City traffic lights (simulated SCATS sites) | `../APIs/trafficControlAPI.py`, `smartcity/lights.py` | Rerouting, Traffic Control checks |
| 9 agents (flood ×3, event ×3, traffic ×3) | `smartcity/agents/` | one check per chain |
| PostgreSQL + PostGIS + TimescaleDB + pgRouting | `db/` | *PostgreSQL extensions*, Flood Scope, Rerouting |
| GDAL/ogr2ogr, osm2pgsql, GeoPandas, rasterio | `loader/`, `smartcity/loader_enrich.py` | *Static layers* |
| scikit-learn | `agents/flood_predictor.py` | *Flood Predicting Agent* |
| FastAPI (Notification, Approval, WebSocket hub) | `smartcity/services/` | Notification, Approval, WebSocket checks |
| SMS (SMSAPI) + Gmail API | `../APIs/notification`, `services/notification.py` | *Notification Agent* (dry-run unless keys set) |
| NGINX gateway: TLS, reverse proxy, OAuth2 + JWT | `deploy/nginx` | *NGINX gateway*, *auth_request* |
| Blob Storage (Azurite locally) | loader + approval | *Blob Storage*, *Approval Service* |
| Key Vault (lowkey-vault emulator locally) | `smartcity/secrets.py` | *Key Vault* |
| React + TypeScript + MapLibre GL | `portal/` | *Portal static bundle*, *WebSocket hub* |
| OpenTelemetry, Prometheus, Grafana | `smartcity/telemetry.py`, `deploy/` | *Prometheus*, *Grafana* |
| pytest, JUnit (XML reports), Postman | `tests/`, `postman/` | `reports/*.xml` |
| Git + GitHub Actions CI/CD, Docker, ACR | `../.github/workflows/thin-slice.yml` | CI run |
| Terraform, AKS, Azure Monitor + Log Analytics | `infra/terraform`, `k8s/` | `terraform validate` / `plan` |

## Not yet exercised (honest gaps for the demonstrator)

- **Azure itself** (AKS, Front Door/WAF, ACR, Key Vault, Azure Monitor): the Terraform and AKS manifest
  are written but not applied. Run `terraform init && terraform validate && terraform plan` with your
  Azure for Students subscription before the demo. Front Door is not in the Terraform yet; add it if
  you want it in the slice.
- **Real SMS/email**: dry-run until `SMSAPI_TOKEN` / `GMAIL_CLIENT_SECRET_FILE` are set in `.env`. SMSAPI
  then runs in test mode (validated, not delivered) unless `SMS_LIVE=1`. Gmail needs a `token.json` made
  once on a laptop with `APIs/notification/Emailapi.py` (browser sign-in), then mounted into the container.
- **Ticketmaster / TomTom** go live when `TICKETMASTER_API_KEY` / `TOMTOM_API_KEY` are in `.env`; until then the
  ingest worker uses fixtures shaped exactly like those modules' return values.
- The **ML model** trains on synthetic data. Replays of archived OPW and Marine Institute storms are the
  iteration-4 task.
