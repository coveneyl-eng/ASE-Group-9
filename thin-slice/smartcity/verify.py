"""Thin-slice verifier: proves every technology in the technical architecture is installed and can talk to the
ones it must interact with. Prints a PASS/FAIL table and writes a JUnit XML report.

    docker compose run --rm verifier          (see scripts/verify.sh)

Set VERIFY_SKIP=grafana,keyvault,... to skip checks for components not deployed in an environment.
"""
import json
import os
import ssl
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt
from confluent_kafka import Consumer
from confluent_kafka.admin import AdminClient

from smartcity import bus, config, db

GATEWAY = os.getenv("GATEWAY_URL", "https://nginx:443")
PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
GRAFANA = os.getenv("GRAFANA_URL", "http://grafana:3000")
SKIP = set(filter(None, os.getenv("VERIFY_SKIP", "").split(",")))
REPORT = Path(os.getenv("VERIFY_REPORT", "reports/thin-slice-junit.xml"))
WATCH = ["flood.readings", "flood.events", "flood.impacts", "flood.forecast", "traffic.reroute", "event.watch",
         "event.plans", "event.transport", "traffic.flow", "traffic.congestion", "traffic.signals",
         "dispatch.approved", "notifications.sent"]

results: list[tuple[str, str, str, float]] = []  # (name, PASS/FAIL/SKIP, detail, seconds)


def check(name: str, key: str = ""):
    def wrap(fn):
        if key and key in SKIP:
            results.append((name, "SKIP", f"VERIFY_SKIP={key}", 0.0))
            return fn
        start = time.time()
        try:
            detail = fn() or ""
            results.append((name, "PASS", str(detail), time.time() - start))
        except Exception as exc:
            results.append((name, "FAIL", f"{type(exc).__name__}: {exc}", time.time() - start))
        return fn
    return wrap


class Tap:
    """Kafka consumer subscribed to every topic before the test traffic is sent."""

    def __init__(self):
        bus.ensure_topics(WATCH)
        self.c = Consumer({**bus._base_conf(), "group.id": f"verify-{uuid.uuid4().hex[:8]}",
                           "auto.offset.reset": "latest", "topic.metadata.refresh.interval.ms": 10000})
        self.c.subscribe(WATCH)
        self.seen: list[tuple[str, dict, float]] = []
        deadline = time.time() + 20
        while not self.c.assignment() and time.time() < deadline:
            self.c.poll(0.2)
        assert self.c.assignment(), "verifier consumer got no partition assignment"
        time.sleep(1)

    def wait_for(self, topic: str, pred=lambda d: True, timeout: float = 15.0) -> dict:
        for t, d, _ in self.seen:
            if t == topic and pred(d):
                return d
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.c.poll(0.2)
            if m is None or m.error():
                continue
            d = json.loads(m.value())
            self.seen.append((m.topic(), d, time.time()))
            if m.topic() == topic and pred(d):
                return d
        raise TimeoutError(f"no matching message on {topic} within {timeout}s")


def lights_held(site_ids: list[str], state: str) -> list[str]:
    """Ask the team's traffic-light API which of these sites are manually held in `state`."""
    from smartcity import lights
    held = [x["site_id"] for x in lights.status(site_ids) if x["mode"] == "manual" and x["state"] == state]
    assert held, f"no light among {site_ids} is held {state}"
    return held


def http(verify: bool = False) -> httpx.Client:
    return httpx.Client(verify=config.MQTT_CA_FILE if verify else False, timeout=10)


def main() -> int:
    tap = Tap()
    trace = {}

    @check("Kafka event bus reachable (SASL/TLS per env), topics listed")
    def _():
        md = AdminClient(bus._base_conf()).list_topics(timeout=10)
        return f"{config.KAFKA_SECURITY_PROTOCOL}; {len(md.topics)} topics"

    @check("PostgreSQL extensions: PostGIS + pgRouting + TimescaleDB", "timescaledb")
    def _():
        with db.connect() as c:
            ext = {r["extname"]: r["extversion"] for r in c.execute(
                "SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','pgrouting','timescaledb')")}
        missing = {"postgis", "pgrouting", "timescaledb"} - ext.keys()
        assert not missing, f"missing {missing} (have {ext})"
        return ext

    @check("PostgreSQL extensions: PostGIS + pgRouting")
    def _():
        with db.connect() as c:
            ext = {r["extname"]: r["extversion"] for r in c.execute(
                "SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','pgrouting')")}
        assert len(ext) == 2, ext
        return ext

    @check("Static layers: ogr2ogr (GDAL) + osm2pgsql + rasterio/GeoPandas DTM enrichment")
    def _():
        with db.connect() as c:
            n = c.execute("SELECT (SELECT count(*) FROM assets) a, (SELECT count(*) FROM cfram_extents) e, "
                          "(SELECT count(*) FROM road_edges) r, (SELECT count(*) FROM osm_line) o, "
                          "(SELECT count(*) FROM assets WHERE elevation_m IS NOT NULL) z").fetchone()
        assert all(n.values()), n
        return n

    @check("Blob Storage (Azurite / Azure Storage): static layers archived")
    def _():
        from azure.storage.blob import BlobServiceClient
        names = [b.name for b in BlobServiceClient.from_connection_string(config.BLOB_CONNECTION_STRING)
                 .get_container_client("static-layers").list_blobs()]
        assert "dtm_sample.tif" in names, names
        return f"{len(names)} blobs"

    @check("Key Vault: JWT signing key readable", "keyvault")
    def _():
        from smartcity import secrets
        assert config.KEY_VAULT_URL, "KEY_VAULT_URL not set"
        return f"secret length {len(secrets.get_secret('jwt-signing-key', config.JWT_SECRET))}"

    # ---- Flood path: sensor -> MQTT/TLS -> bridge -> Kafka -> detector -> scope (PostGIS) -> rerouting
    #      (pgRouting) + notification (SMS/email) -> WebSocket hub
    @check("Sensor simulator -> Mosquitto over TLS (MQTT, QoS 1)")
    def _():
        trace["id"] = uuid.uuid4().hex
        trace["sent"] = datetime.now(timezone.utc)
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"verify-{trace['id'][:6]}")
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
        client.tls_set(ca_certs=config.MQTT_CA_FILE, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client.connect(config.MQTT_HOST, config.MQTT_PORT)
        client.loop_start()
        payload = {"sensor_id": "DODDER-RINGSEND", "kind": "water_level_m", "value": 3.2, "lon": -6.2210,
                   "lat": 53.3385, "observed_at": trace["sent"].isoformat(), "trace_id": trace["id"]}
        client.publish("city/sensors/water_level_m/DODDER-RINGSEND", json.dumps(payload), qos=1).wait_for_publish(5)
        tls = client.socket().version() if hasattr(client.socket(), "version") else "TLS"
        client.loop_stop()
        client.disconnect()
        return f"{tls}, trace {trace['id'][:8]}"

    is_trace = lambda d: d.get("trace_id") == trace.get("id")  # noqa: E731

    @check("MQTT bridge -> Kafka flood.readings")
    def _():
        return tap.wait_for("flood.readings", is_trace)["source"]

    @check("Flood Detector consumes flood.readings -> flood.events (CFRAM threshold from PostGIS)")
    def _():
        e = tap.wait_for("flood.events", is_trace)
        return f"{e['level_m']} m >= {e['threshold_m']} m"

    @check("Flood Scope: PostGIS extent overlay -> flood.impacts (+ TimescaleDB impacts table)")
    def _():
        i = tap.wait_for("flood.impacts", is_trace)
        trace["impact"] = i
        return {a["name"]: a["status"] for a in i["impacts"]}

    @check("Rerouting: pgRouting avoids flooded edges -> traffic.reroute + lights held red (trafficControlAPI)")
    def _():
        r = tap.wait_for("traffic.reroute", is_trace)
        assert r["path_edges"] and not set(r["path_edges"]) & set(r["avoided_edges"]), r
        held = lights_held(r["closed_light_sites"], "red")
        return f"path {r['path_edges']} avoids {r['avoided_edges']}; lights {held} red"

    @check("Notification Agent (FastAPI): SMS (SMSAPI) + email (Gmail API) via APIs/notification, latency <= 5 s")
    def _():
        tap.wait_for("notifications.sent", lambda d: is_trace(d) and d["channel"] == "email", timeout=10)
        with db.connect() as c:
            rows = c.execute("SELECT channel, latency_ms, dry_run FROM notifications WHERE trace_id = %s",
                             (trace["id"],)).fetchall()
        assert {r["channel"] for r in rows} >= {"sms", "email"}, rows
        worst = max(r["latency_ms"] for r in rows)
        assert worst <= 5000, f"latency {worst:.0f} ms over 5 s target"
        mode = "dry-run" if all(r["dry_run"] for r in rows) else "live"
        return f"sensor->alert {worst:.0f} ms ({mode} providers)"

    # ---- Public data ingest -> forecast (scikit-learn), events and traffic agents
    @check("Ingest via team APIs/ (OPW, Met Éireann, Marine, Ticketmaster, TomTom, NTA) -> Kafka")
    def _():
        from smartcity.services import ingest
        counts = ingest.run_once(bus.Publisher())
        tap.wait_for("flood.readings", lambda d: d["source"].startswith("opw"))
        return counts

    @check("Flood Predicting Agent: scikit-learn forecast -> flood.forecast")
    def _():
        f = tap.wait_for("flood.forecast")
        return f"{f['predicted_level_m']} m in {f['horizon_hours']} h ({f['expected_impact']})"

    @check("Event Monitoring -> Event Coordinating (PostGIS venue check) -> Public Transport (osm2pgsql roads)")
    def _():
        from datetime import timedelta
        from smartcity.models import UpcomingEvent
        ev = UpcomingEvent(event_name=f"Verifier match {trace['id'][:6]}", venue="Aviva Stadium", lon=-6.2283,
                           lat=53.3350, expected_attendance=51700,
                           starts_at=datetime.now(timezone.utc) + timedelta(days=3))
        bus.Publisher().publish("event.upcoming", ev)
        same = lambda d: d.get("trace_id") == ev.trace_id  # noqa: E731
        tap.wait_for("event.watch", same)
        p = tap.wait_for("event.plans", same)
        tp = tap.wait_for("event.transport", same)
        return f"{p['event_name']}: access {p['venue_access']}, +{tp['extra_buses']} buses via {tp['routes']}"

    @check("Traffic Monitoring (TomTom flow) -> Traffic Control -> lights held green (trafficControlAPI)")
    def _():
        c = tap.wait_for("traffic.congestion")
        s = tap.wait_for("traffic.signals", lambda d: d["junction_id"] == c["junction_id"])
        held = lights_held(s["site_ids"], "green")
        return f"{c['junction_id']} ({c['level']}) -> lights {held} green {s['seconds']} s"

    # ---- Officials: NGINX (TLS) -> Approval (OAuth2/JWT, roles) -> audit + Blob + Kafka -> Notification
    tokens = {}

    @check("NGINX gateway: HTTPS + OAuth2 password flow issues JWT")
    def _():
        with http() as h:
            for user, pw in [("dispatcher", "dispatch-demo"), ("planner", "planner-demo")]:
                r = h.post(f"{GATEWAY}/api/approval/token", data={"username": user, "password": pw})
                r.raise_for_status()
                tokens[user] = r.json()["access_token"]
        return f"tokens for {sorted(tokens)}"

    @check("NGINX auth_request: protected API rejects missing JWT (401), accepts valid JWT (200)")
    def _():
        with http() as h:
            assert h.get(f"{GATEWAY}/api/notify/notifications/recent").status_code == 401
            ok = h.get(f"{GATEWAY}/api/notify/notifications/recent",
                       headers={"Authorization": f"Bearer {tokens['dispatcher']}"})
            assert ok.status_code == 200, ok.text
        return "401 / 200"

    @check("Approval Service: role check, explicit confirmation, audit log, Blob report, dispatch.approved")
    def _():
        impact = trace["impact"]
        body = {"impact_id": impact["id"], "trace_id": trace["id"], "action": "dispatch_responders", "confirm": True}
        with http() as h:
            denied = h.post(f"{GATEWAY}/api/approval/approvals", json=body,
                            headers={"Authorization": f"Bearer {tokens['planner']}"})
            assert denied.status_code == 403, denied.text
            ok = h.post(f"{GATEWAY}/api/approval/approvals", json=body,
                        headers={"Authorization": f"Bearer {tokens['dispatcher']}"})
            assert ok.status_code == 200, ok.text
        tap.wait_for("dispatch.approved", is_trace)
        from azure.storage.blob import BlobServiceClient
        blob = BlobServiceClient.from_connection_string(config.BLOB_CONNECTION_STRING).get_blob_client(
            config.BLOB_CONTAINER, ok.json()["report_blob"])
        assert blob.exists()
        with db.connect() as c:
            n = c.execute("SELECT count(*) AS n FROM audit_log WHERE payload->>'impact_id' = %s",
                          (impact["id"],)).fetchone()["n"]
        assert n >= 1
        return f"planner 403, dispatcher 200, audit rows {n}, blob {ok.json()['report_blob']}"

    @check("WebSocket hub via NGINX (wss): JWT handshake + live Kafka updates")
    def _():
        from websockets.sync.client import connect
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        url = GATEWAY.replace("https://", "wss://") + f"/ws?token={tokens['dispatcher']}"
        got = []
        with connect(url, ssl=ctx, open_timeout=10) as ws:
            deadline = time.time() + 10
            while time.time() < deadline and not {"hello", "flood.impacts"} <= set(got):
                got.append(json.loads(ws.recv(timeout=5))["topic"])
        assert {"hello", "flood.impacts"} <= set(got), got
        return f"received {got}"

    @check("System-health dashboard API via NGINX: component probes, topic activity, role-checked test flood")
    def _():
        with http() as h:
            assert h.get(f"{GATEWAY}/api/hub/status").status_code == 401
            st = h.get(f"{GATEWAY}/api/hub/status", headers={"Authorization": f"Bearer {tokens['dispatcher']}"})
            assert st.status_code == 200, st.text
            checks = {c["id"]: c["status"] for c in st.json()["checks"]}
            assert checks.get("kafka") == "ok" and checks.get("mosquitto") == "ok", checks
            denied = h.post(f"{GATEWAY}/api/hub/simulate-flood", json={"level_m": 3.0},
                            headers={"Authorization": f"Bearer {tokens['planner']}"})
            assert denied.status_code == 403, denied.text
        counts = {k: list(checks.values()).count(k) for k in ("ok", "degraded", "down", "skipped")}
        return f"{len(checks)} components {counts}; planner cannot send test readings (403)"

    @check("Public status map data via NGINX (no login)")
    def _():
        with http() as h:
            s = h.get(f"{GATEWAY}/api/state").json()
        assert "flood.impacts" in s
        return "flood.impacts present"

    @check("Portal static bundle (React + TypeScript + MapLibre) served by NGINX")
    def _():
        with http() as h:
            html = h.get(f"{GATEWAY}/").text
        assert '<div id="root">' in html and "/assets/" in html, html[:200]
        return "index.html + built assets"

    @check("Prometheus scrapes OpenTelemetry metrics from agents", "prometheus")
    def _():
        time.sleep(6)  # one scrape interval
        q = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": "smartcity_sensor_to_alert_seconds_count"}).json()
        up = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": "sum(up)"}).json()
        assert q["data"]["result"], q
        return f"targets up: {up['data']['result'][0]['value'][1]}, latency series: {len(q['data']['result'])}"

    @check("Grafana: Prometheus datasource + Smart City dashboard provisioned", "grafana")
    def _():
        assert httpx.get(f"{GRAFANA}/api/health").json()["database"] == "ok"
        d = httpx.get(f"{GRAFANA}/api/dashboards/uid/smartcity-thin-slice").json()
        return d["dashboard"]["title"]

    # ---- Report
    width = max(len(r[0]) for r in results)
    print("\n" + "=" * (width + 60))
    for name, status, detail, _ in results:
        print(f"{status:4}  {name:{width}}  {detail[:110]}")
    failed = [r for r in results if r[1] == "FAIL"]
    print("=" * (width + 60))
    print(f"{sum(r[1] == 'PASS' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r[1] == 'SKIP' for r in results)} skipped")

    suite = ET.Element("testsuite", name="thin-slice", tests=str(len(results)), failures=str(len(failed)),
                       skipped=str(sum(r[1] == "SKIP" for r in results)))
    for name, status, detail, secs in results:
        tc = ET.SubElement(suite, "testcase", classname="thin_slice", name=name, time=f"{secs:.2f}")
        if status == "FAIL":
            ET.SubElement(tc, "failure", message=detail)
        elif status == "SKIP":
            ET.SubElement(tc, "skipped", message=detail)
        else:
            ET.SubElement(tc, "system-out").text = detail
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(REPORT, encoding="utf-8", xml_declaration=True)
    print(f"JUnit report: {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
