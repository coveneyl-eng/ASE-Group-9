"""Health checks for the system-health dashboard: one probe per technology in the technical architecture.

Each probe returns quickly (short timeouts), runs in parallel with the others, and reports
ok / degraded / down / skipped with a one-line detail, so one dead component never stalls the page.
"""
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import paho.mqtt.client as mqtt

from smartcity import bus, config, db

TIMEOUT_S = 3.0

# Every agent/worker process exposes OpenTelemetry metrics for Prometheus on :9464 (see telemetry.py).
AGENTS = ["mqtt-bridge", "ingest", "flood-detector", "flood-scope", "flood-predictor", "rerouting",
          "event-monitoring", "event-coordinating", "public-transport", "traffic-monitoring", "traffic-control"]
AGENT_GROUPS = {"mqtt-bridge": "Ingest", "ingest": "Ingest", "flood-detector": "Flood", "flood-scope": "Flood",
                "flood-predictor": "Flood", "rerouting": "Traffic", "traffic-monitoring": "Traffic",
                "traffic-control": "Traffic", "event-monitoring": "Event", "event-coordinating": "Event",
                "public-transport": "Event"}


def agent_metrics_urls() -> dict[str, str]:
    """AGENT_METRICS='name=url,...' overrides the compose defaults (http://<service>:9464/metrics)."""
    urls = {a: f"http://{a}:9464/metrics" for a in AGENTS}
    for pair in filter(None, config.AGENT_METRICS.split(",")):
        name, url = pair.split("=", 1)
        urls[name.strip()] = url.strip()
    return urls


def result(cid, name, group, status, detail, started):
    return {"id": cid, "name": name, "group": group, "status": status, "detail": detail,
            "ms": round((time.time() - started) * 1000)}


def probe(cid, name, group, fn):
    started = time.time()
    try:
        status, detail = fn()
    except Exception as exc:  # a probe failure is the answer "down", never an error page
        status, detail = "down", f"{type(exc).__name__}: {str(exc)[:120]}"
    return result(cid, name, group, status, detail, started)


# ---------- probes: each returns (status, detail) ----------
def mqtt_probe():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"health-{uuid4().hex[:6]}")
    client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    client.tls_set(ca_certs=config.MQTT_CA_FILE, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=5)
    tls = client.socket().version()
    client.disconnect()
    return "ok", f"{tls}, authenticated on :{config.MQTT_PORT}"


def kafka_probe():
    from confluent_kafka.admin import AdminClient
    md = AdminClient(bus._base_conf()).list_topics(timeout=TIMEOUT_S)
    ours = sorted(t for t in md.topics if not t.startswith("_"))
    return "ok", f"{len(ours)} topics, {config.KAFKA_SECURITY_PROTOCOL}"


def postgres_probe():
    with db.connect() as c:
        ext = {r["extname"]: r["extversion"] for r in c.execute(
            "SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','pgrouting','timescaledb')")}
    detail = ", ".join(f"{k} {v}" for k, v in sorted(ext.items()))
    if {"postgis", "pgrouting"} - ext.keys():
        return "down", f"missing extensions; have {detail or 'none'}"
    return ("ok" if "timescaledb" in ext else "degraded"), detail + ("" if "timescaledb" in ext else ", no timescaledb")


def static_layers_probe():
    with db.connect() as c:
        n = c.execute("SELECT (SELECT count(*) FROM assets) AS assets, (SELECT count(*) FROM road_edges) AS edges, "
                      "(SELECT count(*) FROM cfram_extents) AS extents").fetchone()
    status = "ok" if all(n.values()) else "degraded"
    return status, f"{n['assets']} assets, {n['edges']} road edges, {n['extents']} flood extents"


def blob_probe():
    from azure.storage.blob import BlobServiceClient
    svc = BlobServiceClient.from_connection_string(config.BLOB_CONNECTION_STRING,
                                                   connection_timeout=TIMEOUT_S, read_timeout=TIMEOUT_S)
    names = [c.name for c in svc.list_containers()]
    return "ok", f"containers: {', '.join(names) or 'none yet'}"


def keyvault_probe():
    if not config.KEY_VAULT_URL:
        return "skipped", "KEY_VAULT_URL not set (secrets from environment)"
    from smartcity import secrets
    secrets.check("jwt-signing-key", config.JWT_SECRET)  # strict: the services' dev fallback must not look green
    return "ok", "JWT signing key readable"


def http_probe(url, ok_detail, verify=False):
    def run():
        if not url:
            return "skipped", "not configured"
        r = httpx.get(url, timeout=TIMEOUT_S, verify=verify)
        r.raise_for_status()
        return "ok", ok_detail(r)
    return run


def prometheus_probe():
    if not config.PROMETHEUS_URL:
        return "skipped", "not configured"
    r = httpx.get(f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": "up"}, timeout=TIMEOUT_S).json()
    series = r["data"]["result"]
    up = sum(1 for s in series if s["value"][1] == "1")
    return ("ok" if series and up == len(series) else "degraded"), f"{up}/{len(series)} scrape targets up"


def agent_probe(name, url, stats):
    def run():
        httpx.get(url, timeout=TIMEOUT_S).raise_for_status()
        s = stats.get(name)
        if not s:
            return "ok", "running, no decisions yet"
        age = int(time.time() - s["last"].timestamp())
        return "ok", f"{s['n']} decisions, last {age_words(age)} ago"
    return run


def age_words(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


# ---------- aggregate ----------
def decision_stats() -> dict:
    try:
        with db.connect() as c:
            rows = c.execute("SELECT agent, count(*) AS n, max(at) AS last FROM agent_decisions GROUP BY agent")
            return {r["agent"]: r for r in rows}
    except Exception:
        return {}


def latency_stats() -> dict:
    """Sensor-to-alert latency over the last hour, against the 5 s QoS target."""
    try:
        with db.connect() as c:
            r = c.execute("""
                SELECT count(*) AS n,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                       (SELECT latency_ms FROM notifications ORDER BY id DESC LIMIT 1) AS last
                  FROM notifications WHERE at > now() - interval '1 hour'""").fetchone()
        return {"alerts_last_hour": r["n"], "p95_ms": r["p95"], "last_ms": r["last"], "target_ms": 5000}
    except Exception:
        return {"alerts_last_hour": 0, "p95_ms": None, "last_ms": None, "target_ms": 5000}


def run_all(hub_detail: str) -> list[dict]:
    stats = decision_stats()
    probes = [
        ("mosquitto", "Mosquitto (MQTT/TLS)", "Field network", mqtt_probe),
        ("kafka", "Apache Kafka", "Event bus", kafka_probe),
        ("postgres", "PostgreSQL + PostGIS / pgRouting / TimescaleDB", "Data", postgres_probe),
        ("static-layers", "Static layers (GDAL, osm2pgsql, rasterio)", "Data", static_layers_probe),
        ("blob", "Blob Storage", "Data", blob_probe),
        ("keyvault", "Key Vault", "Data", keyvault_probe),
        ("notification", "Notification Agent (FastAPI)", "Communication",
         http_probe(f"{config.NOTIFY_URL}/health", lambda r: "SMS (SMSAPI) + email (Gmail API)")),
        ("approval", "Approval Service (OAuth2 / JWT)", "Communication",
         http_probe(f"{config.APPROVAL_URL}/health", lambda r: "role-checked sign-off, audit log")),
        ("nginx", "NGINX gateway (HTTPS)", "Edge",
         http_probe(config.GATEWAY_URL and f"{config.GATEWAY_URL}/", lambda r: f"HTTP/{r.http_version[-3:]}, TLS")),
        ("traffic-lights", "City traffic-light API", "City systems",
         http_probe(f"{config.TRAFFIC_LIGHTS_URL}/health", lambda r: f"{r.json().get('lights')} SCATS sites")),
        ("prometheus", "Prometheus", "Observability", prometheus_probe),
        ("grafana", "Grafana", "Observability",
         http_probe(config.GRAFANA_URL and f"{config.GRAFANA_URL}/api/health",
                    lambda r: f"database {r.json().get('database')}")),
    ]
    probes += [(a, a.replace("-", " ").title().replace("Mqtt", "MQTT"), f"Agents · {AGENT_GROUPS[a]}",
                agent_probe(a, url, stats)) for a, url in agent_metrics_urls().items()]
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        futures = [pool.submit(probe, *p) for p in probes]
        checks = [f.result() for f in futures]
    checks.append({"id": "ws-hub", "name": "WebSocket hub (FastAPI)", "group": "Communication", "status": "ok",
                   "detail": hub_detail, "ms": 0})
    return checks
