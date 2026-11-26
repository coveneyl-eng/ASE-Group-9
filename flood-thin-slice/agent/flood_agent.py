"""Flood Detector agent: a long-running container that reacts to water level readings on Kafka.

Ported from Vaibhav's thin-slice agent (smartcity/agents/flood_detector.py + bus.py + base.py) and cut down
to fit this thin slice: same Kafka settings and the same database as load_all.py, no MQTT, no Pydantic models.

    ingest (load_all.py) --flood.readings--> THIS AGENT --flood.impacts--> (portal, notifications, ...)
                                                 |
                                                 +--> readings + agent_decisions tables (PostGIS)

For every reading it:
  1. stores it in `readings` (same table load_all.py writes; duplicates are ignored)
  2. for the watched station (Dublin Port tide gauge by default) compares the level to the nearest CFRAM
     node's 10% / 0.5% / 0.1% AEP levels
  3. if a band is active, lists the infrastructure inside that coastal flood extent (with LiDAR depth when
     the dsm raster is loaded), publishes a flood.impacts event and records the decision in agent_decisions.
     When the level drops back below every band it publishes one "clear" event.

Environment (same names as load_all.py, so one set of settings serves both containers):
    DB_URL, KAFKA, KAFKA_TOPIC (default flood.readings),
    KAFKA_SECURITY_PROTOCOL / KAFKA_SASL_MECHANISM / KAFKA_SASL_USERNAME / KAFKA_SASL_PASSWORD
  Agent only:
    KAFKA_GROUP     default flood-agent (must differ from load_all's flood-detector group)
    IMPACT_TOPIC    default flood.impacts
    WATCH_STATION   default "Dublin Port"
    OFFSET_RESET    earliest (default: also handles readings sent before the agent started) or latest
    MAX_ASSETS      assets listed in one event, default 200 (the count is always the full number)

Demo without waiting for a real flood:  python flood_agent.py --send 2.9
(publishes one simulated Dublin Port reading to flood.readings, then exits; the running agent picks it up).
"""
import datetime as dt
import json
import logging
import os
import signal
import sys
import time
import uuid

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DB_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood")
KAFKA = os.getenv("KAFKA", "localhost:9092")
READINGS_TOPIC = os.getenv("KAFKA_TOPIC", "flood.readings")
IMPACT_TOPIC = os.getenv("IMPACT_TOPIC", "flood.impacts")
GROUP = os.getenv("KAFKA_GROUP", "flood-agent")
WATCH_STATION = os.getenv("WATCH_STATION", "Dublin Port")
OFFSET_RESET = os.getenv("OFFSET_RESET", "earliest")
MAX_ASSETS = int(os.getenv("MAX_ASSETS", "200"))
DUBLIN_PORT = (-6.2217, 53.3457)  # Marine Institute tide gauge, WGS84 (same point as load_all.py)
NAME = "flood-agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger(NAME)


# ---------------- Kafka (from Vaibhav's smartcity/bus.py) ----------------

def kafka_config(**extra):
    """Plain Kafka by default; SASL_SSL (Event Hubs, Confluent Cloud) when the env vars are set. Same as load_all.py."""
    conf = {"bootstrap.servers": KAFKA, **extra}
    for env, key in (("KAFKA_SECURITY_PROTOCOL", "security.protocol"), ("KAFKA_SASL_MECHANISM", "sasl.mechanisms"),
                     ("KAFKA_SASL_USERNAME", "sasl.username"), ("KAFKA_SASL_PASSWORD", "sasl.password")):
        if os.getenv(env):
            conf[key] = os.environ[env]
    return conf


def ensure_topics(topics):
    """Create missing topics up front. A consumer that subscribes before its topic exists only notices it at the
    next metadata refresh, so without this the agent can sit idle for minutes (Vaibhav's CI fix, db08231)."""
    admin = AdminClient(kafka_config())
    try:
        existing = set(admin.list_topics(timeout=15).topics)
    except KafkaException as exc:
        raise SystemExit(f"Cannot reach Kafka at {KAFKA}: {exc}")
    missing = [t for t in topics if t not in existing]
    if not missing:
        return
    for topic, fut in admin.create_topics([NewTopic(t, num_partitions=1, replication_factor=1) for t in missing]).items():
        try:
            fut.result(15)
            log.info("created topic %s", topic)
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:  # another container may have just made it
                log.warning("could not create topic %s (%s); create it by hand if the agent stays idle", topic, exc)


class Publisher:
    def __init__(self):
        self._producer = Producer(kafka_config(**{"linger.ms": 5, "acks": "all"}))

    def publish(self, topic, key, message):
        self._producer.produce(topic, key=key.encode(), value=json.dumps(message, default=str).encode())
        left = self._producer.flush(10)
        if left:
            raise RuntimeError(f"{topic}: message not delivered to Kafka at {KAFKA}")


# ---------------- database ----------------

db = create_engine(DB_URL, pool_pre_ping=True)


def wait_for_db(seconds=float(os.getenv("DB_WAIT_SECONDS", "120"))):
    deadline = time.time() + seconds
    while True:
        try:
            with db.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception as e:
            if time.time() > deadline:
                sys.exit(f"Cannot reach the database at {db.url.render_as_string(hide_password=True)}: "
                         f"{type(e).__name__}: {str(e).strip().splitlines()[0][:200]}")
            log.info("waiting for the database...")
            time.sleep(5)


def setup_db():
    wait_for_db()
    with db.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS readings(
            time timestamptz NOT NULL, source text, station text, level_m double precision,
            PRIMARY KEY (time, source, station))"""))
        # Every decision an agent makes (Vaibhav's agent_decisions table, used for per-agent statistics)
        c.execute(text("""CREATE TABLE IF NOT EXISTS agent_decisions(
            id bigserial PRIMARY KEY, time timestamptz NOT NULL DEFAULT now(),
            agent text NOT NULL, trace_id text, decision jsonb NOT NULL)"""))


def table_exists(c, name):
    return c.execute(text("SELECT to_regclass(:t) IS NOT NULL"), dict(t=name)).scalar()


def decide(trace_id, decision):
    with db.begin() as c:
        c.execute(text("INSERT INTO agent_decisions (agent, trace_id, decision) VALUES (:a, :t, CAST(:d AS jsonb))"),
                  dict(a=NAME, t=trace_id, d=json.dumps(decision, default=str)))


# ---------------- the agent ----------------

def active_band(c, level_m):
    """Nearest CFRAM node to the gauge -> which AEP band the level has reached (None = below 10%)."""
    node = c.execute(text("""SELECT "WL_10PC", "WL_05PC", "WL_01PC" FROM cfram_nodes WHERE "WL_10PC" > 0
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 2157) LIMIT 1"""),
        dict(x=DUBLIN_PORT[0], y=DUBLIN_PORT[1])).first()
    if node is None:
        return None, None
    levels = {"10%": node.WL_10PC, "0.5%": node.WL_05PC, "0.1%": node.WL_01PC}
    band = next((b for b in ("0.1%", "0.5%", "10%") if level_m >= levels[b]), None)
    return band, levels


def grade(kind, depth):
    """safe / caution / unsafe, same thresholds as load_all.py (roads tolerate a little water)."""
    if depth is None:
        return "unsafe"
    if depth < (0.10 if kind == "road" else 0):
        return "safe"
    return "caution" if depth < (0.30 if kind == "road" else 0.15) else "unsafe"


def impacts(c, band, level_m):
    """Infrastructure inside the active coastal extent, with LiDAR water depth when the dsm raster is loaded."""
    depth = """(SELECT :lvl - max(ST_Value(d.rast, ST_PointOnSurface(i.geometry))) FROM dsm d
                WHERE ST_Intersects(d.rast, ST_PointOnSurface(i.geometry)))""" if table_exists(c, "dsm") else "NULL"
    rows = c.execute(text(f"""
        WITH zone AS (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep = :band)
        SELECT i.kind, coalesce(i.name, i.osm_id) AS name, i.osm_id, {depth} AS depth,
               ST_X(ST_Transform(ST_PointOnSurface(i.geometry), 4326)) AS lon,
               ST_Y(ST_Transform(ST_PointOnSurface(i.geometry), 4326)) AS lat
        FROM infrastructure i, zone WHERE ST_Intersects(i.geometry, zone.g)
        ORDER BY i.kind, name"""), dict(band=band, lvl=level_m)).all()
    people = None
    if table_exists(c, "small_areas"):
        people = c.execute(text("""SELECT count(*) FROM small_areas s,
            (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep = :band) z
            WHERE ST_Intersects(s.geometry, z.g)"""), dict(band=band)).scalar()
    assets = [{"kind": r.kind, "name": r.name, "osm_id": r.osm_id, "grade": grade(r.kind, r.depth),
               "depth_m": None if r.depth is None else round(r.depth, 2),
               "lon": round(r.lon, 6), "lat": round(r.lat, 6)} for r in rows]
    return assets, people


class FloodAgent:
    def __init__(self):
        self.publisher = Publisher()
        self.last_band = None
        self.processed = 0

    def handle(self, r):
        with db.begin() as c:
            c.execute(text("INSERT INTO readings VALUES (:t, :s, :st, :v) ON CONFLICT DO NOTHING"),
                      dict(t=r["time"], s=r["source"], st=r["station"], v=r["level_m"]))
        self.processed += 1
        if r["station"] != WATCH_STATION:
            return
        trace = r.get("id") or str(uuid.uuid4())
        with db.connect() as c:
            missing = [t for t in ("cfram_nodes", "flood_extent_coast", "infrastructure") if not table_exists(c, t)]
            if missing:
                log.warning("%s %.2f m, but %s not loaded yet (run the ingest first)", r["station"], r["level_m"],
                            ", ".join(missing))
                return
            band, levels = active_band(c, r["level_m"])
            if band is None:
                log.info("%s %.2f m (%s): below the 10%% AEP level %.2f m, no flood", r["station"], r["level_m"],
                         r["source"], levels["10%"] if levels else float("nan"))
                if self.last_band is not None:  # the water has gone back down: tell everyone once
                    event = {"id": str(uuid.uuid4()), "trace_id": trace, "status": "clear", "station": r["station"],
                             "level_m": r["level_m"], "observed_at": r["time"], "decided_at": now()}
                    self.publisher.publish(IMPACT_TOPIC, r["station"], event)
                    decide(trace, {"flood": False, "station": r["station"], "level_m": r["level_m"]})
                    log.info("published CLEAR to %s", IMPACT_TOPIC)
                self.last_band = None
                return
            assets, people = impacts(c, band, r["level_m"])
        counts = {}
        for a in assets:
            counts.setdefault(a["kind"], {}).setdefault(a["grade"], 0)
            counts[a["kind"]][a["grade"]] += 1
        event = {"id": str(uuid.uuid4()), "trace_id": trace, "status": "flood", "station": r["station"],
                 "source": r["source"], "level_m": r["level_m"], "band": band, "cfram_levels_m": levels,
                 "asset_count": len(assets), "by_kind": counts, "small_areas": people,
                 "assets": assets[:MAX_ASSETS], "observed_at": r["time"], "decided_at": now()}
        self.publisher.publish(IMPACT_TOPIC, r["station"], event)
        decide(trace, {"flood": True, "station": r["station"], "level_m": r["level_m"], "band": band,
                       "asset_count": len(assets), "by_kind": counts, "small_areas": people})
        self.last_band = band
        log.info("FLOOD %s %.2f m >= %s AEP level: %d assets (%s), %s small areas -> %s (trace %s)",
                 r["station"], r["level_m"], band, len(assets),
                 ", ".join(f"{k} {sum(v.values())}" for k, v in sorted(counts.items())), people, IMPACT_TOPIC, trace)

    def run(self):
        """Consume forever (Vaibhav's bus.consume): a bad message never kills the agent, and SIGTERM closes the
        consumer cleanly so a restarted container resumes from the committed offset straight away."""
        stop = []
        signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        signal.signal(signal.SIGINT, lambda *_: stop.append(1))
        ensure_topics([READINGS_TOPIC, IMPACT_TOPIC])
        consumer = Consumer(kafka_config(**{"group.id": GROUP, "auto.offset.reset": OFFSET_RESET,
                                            "enable.auto.commit": True, "topic.metadata.refresh.interval.ms": 10000}))
        consumer.subscribe([READINGS_TOPIC])
        log.info("%s consuming %s from %s (group %s), publishing %s", NAME, READINGS_TOPIC, KAFKA, GROUP, IMPACT_TOPIC)
        heartbeat = time.time()
        try:
            while not stop:
                if time.time() - heartbeat > 60:
                    log.info("alive: %d readings handled so far", self.processed)
                    heartbeat = time.time()
                msg = consumer.poll(0.5)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.warning("kafka error: %s", msg.error())
                    continue
                try:
                    reading = json.loads(msg.value())
                    reading["level_m"] = float(reading["level_m"])
                    for k in ("source", "station", "time"):
                        reading[k]  # noqa: B018  (KeyError -> invalid message)
                except Exception as exc:
                    log.error("invalid message on %s: %s", msg.topic(), exc)
                    continue
                try:
                    self.handle(reading)
                except Exception:
                    log.exception("handler failed for reading %s", reading.get("id"))
        finally:
            consumer.close()
            log.info("stopped after %d readings", self.processed)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def send_simulated(level_m):
    """Publish one fake Dublin Port reading, in the same format load_all.py's ingest uses."""
    ensure_topics([READINGS_TOPIC])
    reading = {"id": str(uuid.uuid4()), "source": "simulated", "station": WATCH_STATION,
               "level_m": level_m, "time": now()}
    Publisher().publish(READINGS_TOPIC, WATCH_STATION, reading)
    print(f"sent {reading} to {READINGS_TOPIC}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--send":
        send_simulated(float(sys.argv[2]))
    else:
        setup_db()
        FloodAgent().run()
