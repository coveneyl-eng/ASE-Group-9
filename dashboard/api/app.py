"""Dashboard API for the flood thin slice (flood-thin-slice/load_all.py).

Reads the same PostgreSQL database and Kafka topic that load_all.py writes, using the same environment
variables, so it points at the local compose stack or at the Azure resources without code changes:
    DB_URL, KAFKA, KAFKA_TOPIC, KAFKA_SECURITY_PROTOCOL, KAFKA_SASL_MECHANISM, KAFKA_SASL_USERNAME, KAFKA_SASL_PASSWORD

    uvicorn api.app:app --port 8080        (from the dashboard/ folder)
"""
import asyncio
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from api import flood

logging.basicConfig(level=logging.INFO, format="%(asctime)s dashboard %(levelname)s %(message)s")
log = logging.getLogger("dashboard")

DB_URL = os.getenv("DB_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood")
KAFKA = os.getenv("KAFKA", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "flood.readings")
WEB_DIST = Path(os.getenv("WEB_DIST", Path(__file__).resolve().parent.parent / "web" / "dist"))
CACHE_S = 5.0

# load_all.py source name -> table it writes, grouped as in its output
LAYERS = [
    ("Live feeds", "opw_waterlevel", "opw_latest"),
    ("Live feeds", "marine_tide_gauges", "tide_readings"),
    ("Live feeds", "met_warnings", "met_warnings"),
    ("Live feeds", "met_point_forecast", "met_forecast"),
    ("Live feeds", "nta_gtfs_static", "bus_stops"),
    ("Live feeds", "nta_gtfs_realtime", "gtfsr_trip_updates"),
    ("Static layers", "cfram_nodes", "cfram_nodes"),
    ("Static layers", "cfram_river_extents", "flood_extent_river"),
    ("Static layers", "cfram_coastal_extents", "flood_extent_coast"),
    ("Static layers", "icwws_coastal_levels", "icwws_points"),
    ("Static layers", "gsi_lidar_dsm", "dsm"),
    ("Static layers", "osm_infrastructure", "infrastructure"),
    ("Static layers", "cso_small_areas", "small_areas"),
    ("Static layers", "cso_saps_population", "saps"),
    ("Kafka → database", "kafka_to_readings", "readings"),
]
EXTENSIONS = ["postgis", "postgis_raster", "timescaledb", "pgrouting"]

engine = create_engine(DB_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
@asynccontextmanager
async def lifespan(_app):
    """Start the Kafka → WebSocket feed thread with the app and stop it on shutdown."""
    global loop
    loop = asyncio.get_running_loop()
    feed = threading.Thread(target=consume_forever, daemon=True)
    feed.start()
    yield
    stopping.set()
    feed.join(timeout=5)


app = FastAPI(title="Flood thin slice dashboard", lifespan=lifespan)


def kafka_config(**extra) -> dict:
    """Same as load_all.kafka_config: plain localhost Kafka, or SASL_SSL (Event Hubs) when the env vars are set."""
    conf = {"bootstrap.servers": KAFKA, **extra}
    for env, key in (("KAFKA_SECURITY_PROTOCOL", "security.protocol"), ("KAFKA_SASL_MECHANISM", "sasl.mechanisms"),
                     ("KAFKA_SASL_USERNAME", "sasl.username"), ("KAFKA_SASL_PASSWORD", "sasl.password")):
        if os.getenv(env):
            conf[key] = os.environ[env]
    return conf


# ---------------- health ----------------
_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def timed(name: str, fn) -> dict:
    start = time.time()
    try:
        status, detail = fn()
    except Exception as exc:  # a failed probe is the answer "down", never an error page
        status, detail = "down", f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:160]}"
    return {"name": name, "status": status, "detail": detail, "ms": round((time.time() - start) * 1000)}


def db_probe():
    with engine.connect() as c:
        version = c.execute(text("SHOW server_version")).scalar()
    return "ok", f"PostgreSQL {version}"


def extensions_probe():
    with engine.connect() as c:
        have = {r.extname: r.extversion for r in c.execute(text("SELECT extname, extversion FROM pg_extension"))}
    detail = ", ".join(f"{e} {have[e]}" if e in have else f"{e} missing" for e in EXTENSIONS)
    if "postgis" not in have:
        return "down", detail
    return ("ok" if all(e in have for e in EXTENSIONS) else "degraded"), detail


def kafka_probe():
    md = AdminClient(kafka_config()).list_topics(timeout=5)
    if KAFKA_TOPIC not in md.topics:
        return "degraded", f"reachable, but topic {KAFKA_TOPIC} not created yet ({len(md.topics)} topics)"
    parts = len(md.topics[KAFKA_TOPIC].partitions)
    return "ok", f"topic {KAFKA_TOPIC}: {parts} partition{'s' if parts != 1 else ''}"


def layers() -> list[dict]:
    out = []
    with engine.connect() as c:
        c.execute(text("SET statement_timeout = 5000"))
        for group, source, table in LAYERS:
            if not flood.exists(c, table):
                out.append({"group": group, "source": source, "table": table, "status": "missing", "rows": None,
                            "detail": "not loaded"})
                continue
            rows = c.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()
            detail = f"{rows:,} row{'s' if rows != 1 else ''}"
            if table == "readings" and rows:
                newest = c.execute(text("SELECT max(time) FROM readings")).scalar()
                detail += f", newest {newest:%d %b %H:%M} UTC"
            out.append({"group": group, "source": source, "table": table, "status": "ok" if rows else "empty",
                        "rows": rows, "detail": detail})
    return out


@app.get("/api/health")
def health():
    def run():
        with ThreadPoolExecutor(3) as pool:
            probes = [pool.submit(timed, *p) for p in (("PostgreSQL", db_probe), ("Extensions", extensions_probe),
                                                        ("Kafka", kafka_probe))]
            components = [p.result() for p in probes]
        try:
            data = layers()
        except Exception as exc:
            data, components[0]["detail"] = [], f"{components[0]['detail']} (layers unreadable: {exc})"
        return {"components": components, "layers": data}
    body = cached("health", run)
    return {**body, "live": {"connected_clients": len(clients), "messages_seen": stats["count"],
                             "last_message_s_ago": None if stats["last"] is None else round(time.time() - stats["last"])},
            "generated_at": time.time()}


# ---------------- readings + flood check ----------------
@app.get("/api/readings")
def readings():
    try:
        with engine.connect() as c:
            if not flood.exists(c, "readings"):
                return {"latest": [], "dublin_port": []}
            latest = c.execute(text("""SELECT DISTINCT ON (source, station) source, station, level_m, time
                FROM readings ORDER BY source, station, time DESC""")).all()
            series = c.execute(text("""SELECT time, level_m FROM readings WHERE station = 'Dublin Port'
                AND source <> 'simulated' AND time > now() - interval '48 hours' ORDER BY time LIMIT 1000""")).all()
    except Exception as exc:
        raise HTTPException(503, f"database unavailable: {exc}") from exc
    return {"latest": [{"source": r.source, "station": r.station, "level_m": r.level_m, "time": r.time.isoformat()}
                       for r in latest],
            "dublin_port": [{"time": r.time.isoformat(), "level_m": r.level_m} for r in series]}


@app.get("/api/flood")
def flood_check(level: float | None = None):
    """Flood check on the latest real Dublin Port reading, or a what-if level (?level=2.9)."""
    try:
        return cached(f"flood:{level}", lambda: flood.check(engine, level))
    except Exception as exc:
        raise HTTPException(503, f"flood check failed: {exc}") from exc


# ---------------- simulate a reading through Kafka ----------------
class Simulate(BaseModel):
    level_m: float = Field(2.9, ge=-3, le=10)


@app.post("/api/simulate")
def simulate(req: Simulate):
    """Publish one Dublin Port reading on the Kafka topic, in load_all.publish_reading's exact format."""
    reading = {"id": str(uuid.uuid4()), "source": "simulated", "station": "Dublin Port", "level_m": req.level_m,
               "time": dt.datetime.now(dt.timezone.utc).isoformat()}
    errors = []
    producer = Producer(kafka_config())
    producer.produce(KAFKA_TOPIC, json.dumps(reading).encode(), key=b"Dublin Port",
                     on_delivery=lambda err, msg: err and errors.append(str(err)))
    if producer.flush(10) or errors:
        raise HTTPException(502, f"Kafka did not accept the reading: {errors or 'timed out'}")
    log.info("simulated Dublin Port reading %.2f m published (%s)", req.level_m, reading["id"])
    return reading


# ---------------- live Kafka feed over WebSocket ----------------
clients: set[WebSocket] = set()
recent: deque = deque(maxlen=50)
stats = {"count": 0, "last": None}
stopping = threading.Event()
loop: asyncio.AbstractEventLoop | None = None


def ensure_topic() -> None:
    """Create the topic if missing: a consumer that subscribes before it exists waits minutes to notice it.
    Best effort: some managed Kafka services refuse topic creation, and then load_all.py's producer creates it."""
    try:
        admin = AdminClient(kafka_config())
        if KAFKA_TOPIC not in admin.list_topics(timeout=5).topics:
            admin.create_topics([NewTopic(KAFKA_TOPIC, num_partitions=1, replication_factor=1)])[KAFKA_TOPIC].result(10)
    except Exception as exc:
        log.warning("could not ensure topic %s: %s", KAFKA_TOPIC, exc)


def consume_forever() -> None:
    while not stopping.is_set():
        try:
            ensure_topic()
            consumer = Consumer(kafka_config(**{"group.id": f"dashboard-{uuid.uuid4().hex[:8]}",
                                                "auto.offset.reset": "latest", "enable.auto.commit": False,
                                                "topic.metadata.refresh.interval.ms": 10000}))
            consumer.subscribe([KAFKA_TOPIC])
            try:
                while not stopping.is_set():
                    msg = consumer.poll(0.5)
                    if msg is None:
                        continue
                    if msg.error():
                        if msg.error().code() != KafkaError._PARTITION_EOF:
                            log.warning("kafka: %s", msg.error())
                        continue
                    try:
                        reading = json.loads(msg.value())
                    except ValueError:
                        continue
                    payload = {"reading": reading, "partition": msg.partition(), "offset": msg.offset(),
                               "received_at": dt.datetime.now(dt.timezone.utc).isoformat()}
                    recent.appendleft(payload)
                    stats["count"] += 1
                    stats["last"] = time.time()
                    if loop:
                        asyncio.run_coroutine_threadsafe(broadcast(payload), loop)
            finally:
                consumer.close()
        except Exception as exc:  # Kafka down: keep retrying, the health panel shows it red meanwhile
            log.warning("live feed consumer stopped (%s); retrying in 5 s", exc)
            stopping.wait(5)


async def broadcast(payload: dict) -> None:
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception:
            clients.discard(ws)


@app.websocket("/api/live")
async def live(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    for payload in reversed(recent):
        await ws.send_json(payload)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


# ---------------- the React app ----------------
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
