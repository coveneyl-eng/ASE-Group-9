"""Hello-world thin slice: load every flood data source for Dublin city, stream the live
water level readings through Kafka, then list infrastructure in the flood zone.

The "sensors" are the OPW water level and Marine Institute tide gauge APIs. The ingest step
polls them and publishes every reading to Kafka (flood.readings); the detector step consumes
that topic and writes the readings to the database, where the flood check picks them up.

    docker compose up -d
    pip install -r requirements.txt
    python load_all.py                  # SIM_LEVEL=2.9 to force a reading

Every setting comes from an environment variable, so the same image runs on a laptop or on Azure:
    DB_URL            SQLAlchemy URL; on Azure add ?sslmode=require
    KAFKA             bootstrap servers, e.g. <namespace>.servicebus.windows.net:9093 for Event Hubs
    KAFKA_TOPIC       default flood.readings (on Event Hubs, create an event hub with this name)
    KAFKA_GROUP       consumer group, default flood-detector
    KAFKA_SECURITY_PROTOCOL / KAFKA_SASL_MECHANISM / KAFKA_SASL_USERNAME / KAFKA_SASL_PASSWORD
                      for Event Hubs: SASL_SSL / PLAIN / $ConnectionString / <connection string>
    SKIP_KAFKA=1      write readings straight to the database (when no Kafka is deployed)
    CACHE             folder for big downloads, default ./data (mount a volume to keep it between runs)
    DB_WAIT_SECONDS   how long to wait for the database on start, default 120

Every call to an outside service lives in ../APIs (opwAPI, marineTideAPI, metEireannAPI,
busAPI, gsiLidarAPI, osmAPI, csoAPI). This file only shapes the data and loads it into PostGIS.
"""
import io, json, os, sys, time, uuid, zipfile, datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "APIs"))
import busAPI, csoAPI, gsiLidarAPI, marineTideAPI, metEireannAPI, opwAPI, osmAPI

import pandas as pd
import geopandas as gpd
from shapely.geometry import box, Point, LineString, Polygon
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DB_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood")
KAFKA = os.getenv("KAFKA", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "flood.readings")
CACHE = Path(os.getenv("CACHE", "data")); CACHE.mkdir(parents=True, exist_ok=True)


def kafka_config(**extra):
    """Plain localhost Kafka by default; SASL_SSL (Azure Event Hubs, Confluent Cloud) when the env vars are set."""
    conf = {"bootstrap.servers": KAFKA, **extra}
    for env, key in (("KAFKA_SECURITY_PROTOCOL", "security.protocol"), ("KAFKA_SASL_MECHANISM", "sasl.mechanisms"),
                     ("KAFKA_SASL_USERNAME", "sasl.username"), ("KAFKA_SASL_PASSWORD", "sasl.password")):
        if os.getenv(env):
            conf[key] = os.environ[env]
    return conf


W, S, E, N = -6.39, 53.29, -6.10, 53.42          # Dublin city, WGS84
ITM = 2157                                        # Irish Transverse Mercator, metres
DUBLIN = gpd.GeoSeries([box(W, S, E, N)], crs=4326)
DUBLIN_PORT = Point(-6.2217, 53.3457)             # Marine Institute tide gauge

db = create_engine(DB_URL)
status = {}


def source(name):
    """Run one loader; record ok / failed so one dead source does not stop the rest."""
    def wrap(fn):
        def run(*a):
            try:
                status[name] = f"ok    {fn(*a)}"
            except Exception as e:
                status[name] = f"FAIL  {type(e).__name__}: {str(e)[:110]}"
            print(f"{name:<22}{status[name]}")
        return run
    return wrap


def need(data, what):
    """The APIs modules print the error and return None on failure; turn that into a FAIL line."""
    if data is None:
        raise RuntimeError(f"{what} request failed (see message above)")
    return data


def cached(download, name, *args):
    """Download a big file once into data/, using one of the APIs download functions."""
    path = CACHE / name
    if not path.exists():
        need(download(*args, path), name)
    return path


def to_db(gdf, table):
    gdf.to_crs(ITM).to_postgis(table, db, if_exists="replace", index=False)
    return f"{len(gdf)} rows -> {table}"


USE_KAFKA = os.getenv("SKIP_KAFKA") != "1" and os.getenv("SKIP_SENSOR_HOP") != "1"
_producer = None
published = []        # ids of the readings this run sent to Kafka


def publish_reading(source_name, station, level_m, t):
    """Ingest: send one sensor reading to Kafka. If Kafka is switched off or rejects it, store it directly."""
    global _producer
    reading = {"id": str(uuid.uuid4()), "source": source_name, "station": station,
               "level_m": float(level_m), "time": t.isoformat() if hasattr(t, "isoformat") else str(t)}
    if not USE_KAFKA:
        return save_reading(source_name, station, level_m, reading["time"])
    if _producer is None:
        from confluent_kafka import Producer
        _producer = Producer(kafka_config())
    fallback = lambda err, msg: err and save_reading(source_name, station, level_m, reading["time"])
    _producer.produce(KAFKA_TOPIC, json.dumps(reading).encode(), key=station.encode(), on_delivery=fallback)
    _producer.poll(0)
    published.append(reading["id"])


def save_reading(source_name, station, level_m, t):
    with db.begin() as c:
        c.execute(text("INSERT INTO readings VALUES (:t, :s, :st, :v) ON CONFLICT DO NOTHING"),
                  dict(t=t, s=source_name, st=station, v=level_m))


def wait_for_db():
    """On Azure the database may still be starting; wait, then stop with one clear line instead of a traceback."""
    deadline = time.time() + float(os.getenv("DB_WAIT_SECONDS", "120"))
    while True:
        try:
            with db.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception as e:
            if time.time() > deadline:
                safe = db.url.render_as_string(hide_password=True)
                sys.exit(f"Cannot reach the database at {safe}: {type(e).__name__}: {str(e).strip().splitlines()[0][:200]}\n"
                         "Set DB_URL (and on Azure add ?sslmode=require and allow this container's IP).")
            print("Waiting for the database...", flush=True)
            time.sleep(5)


def setup_db():
    wait_for_db()
    for ext in ("postgis", "postgis_raster", "timescaledb", "pgrouting"):
        try:  # one at a time, so a managed database without e.g. TimescaleDB still works
            with db.begin() as c:
                c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext} CASCADE"))
        except Exception as e:
            if ext == "postgis":
                sys.exit(f"PostGIS is required but could not be enabled: {str(e).strip().splitlines()[0][:200]}\n"
                         "On Azure Database for PostgreSQL, add POSTGIS to the azure.extensions server parameter.")
            print(f"{'db_extension':<22}WARN  {ext} not available, carrying on without it")
    with db.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS readings(
            time timestamptz NOT NULL, source text, station text, level_m double precision,
            PRIMARY KEY (time, source, station))"""))
        if c.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'timescaledb'")).scalar():
            c.execute(text("SELECT create_hypertable('readings', 'time', if_not_exists => TRUE)"))


# ---------------- live feeds ----------------

@source("opw_waterlevel")
def load_opw():
    gdf = gpd.read_file(io.BytesIO(need(opwAPI.latestWaterLevels(), "OPW water levels")))
    gdf = gdf.clip(DUBLIN.to_crs(gdf.crs))
    for r in gdf[gdf.value.notna()].itertuples():
        publish_reading("opw", f"{r.station_ref}_{r.sensor_ref}", float(r.value), r.datetime)
    return to_db(gdf, "opw_latest")


@source("marine_tide_gauges")
def load_tides():
    t = need(marineTideAPI.tideGaugeReadings("Dublin Port|Howth.*", hours=2), "Marine Institute tide gauges")
    df = pd.DataFrame(t["rows"], columns=t["columnNames"])
    df = df[df.QC_Flag.astype(str) != "9"]  # 9 = missing; live rows are 0 (not yet QC'd), 1 = good
    for r in df.itertuples():
        publish_reading("marine", r.station_id, float(r.Water_Level_OD_Malin), r.time)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=4326)
    return to_db(gdf, "tide_readings")


@source("met_warnings")
def load_warnings():
    warnings = need(metEireannAPI.weatherWarnings(), "Met Eireann warnings")
    pd.DataFrame({"raw": [json.dumps(w) for w in warnings]}).to_sql("met_warnings", db, if_exists="replace", index=False)
    return f"{len(warnings)} active warnings -> met_warnings"


@source("met_point_forecast")
def load_forecast():
    root = ET.fromstring(need(metEireannAPI.pointForecast(53.35, -6.26), "Met Eireann forecast"))
    rows = [(t.get("from"), t.get("to"), float(p.get("value")))
            for t in root.iter("time") for p in t.iter("precipitation")]
    pd.DataFrame(rows, columns=["from", "to", "precip_mm"]).to_sql("met_forecast", db, if_exists="replace", index=False)
    return f"{len(rows)} rainfall periods -> met_forecast"


@source("nta_gtfs_static")
def load_gtfs():
    z = zipfile.ZipFile(cached(busAPI.DublinBusTimetableDownload, "gtfs_dublin_bus.zip"))
    stops = pd.read_csv(z.open("stops.txt"))
    gdf = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), crs=4326).clip(DUBLIN)
    pd.read_csv(z.open("routes.txt")).to_sql("bus_routes", db, if_exists="replace", index=False)
    return to_db(gdf, "bus_stops")


@source("nta_gtfs_realtime")
def load_gtfsr():
    feed = json.loads(need(busAPI.BusTripUpdatesQuery(), "NTA GTFS-Realtime"))
    pd.DataFrame({"raw": [json.dumps(e) for e in feed["entity"]]}).to_sql("gtfsr_trip_updates", db, if_exists="replace", index=False)
    return f"{len(feed['entity'])} trip updates -> gtfsr_trip_updates"


# ---------------- static layers ----------------

@source("cfram_nodes")
def load_nodes():
    path = cached(opwAPI.downloadCframNodes, "cfram_nodes.zip")
    gdf = gpd.read_file(f"zip://{path}", bbox=DUBLIN)
    return to_db(gdf, "cfram_nodes")


def load_extents(download, key, table):
    path = cached(download, f"{key}.zip")
    parts = []
    for shp in [n for n in zipfile.ZipFile(path).namelist() if n.endswith(".shp")]:
        gdf = gpd.read_file(f"zip://{path}!{shp}", bbox=DUBLIN)
        gdf["aep"] = {"0010": "10%", "0100": "1%", "0200": "0.5%", "1000": "0.1%"}[shp[-8:-4]]
        parts.append(gdf[["aep", "geometry"]])
    return to_db(gpd.GeoDataFrame(pd.concat(parts), crs=parts[0].crs), table)


load_river = source("cfram_river_extents")(lambda: load_extents(opwAPI.downloadCframRiverExtents, "cfram_river", "flood_extent_river"))
load_coast = source("cfram_coastal_extents")(lambda: load_extents(opwAPI.downloadCframCoastalExtents, "cfram_coast", "flood_extent_coast"))


@source("icwws_coastal_levels")
def load_icwws():
    df = pd.read_csv(cached(opwAPI.downloadCoastalExtremeLevels, "icwws.csv"))
    df.columns = [c.replace("%", "pc").replace("+", "plus").replace(".", "_") for c in df.columns]
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.Easting, df.Northing), crs=ITM)
    return to_db(gdf.clip(DUBLIN.to_crs(ITM)), "icwws_points")


def raster_wkb(band, transform, srid, nodata):
    """One PostGIS raster tile as WKB, built in Python, so the database needs no GDAL drivers
    (Azure Database for PostgreSQL does not let you enable them)."""
    import struct
    import numpy as np
    h, w = band.shape
    head = struct.pack("<BHHddddddiHH", 1, 0, 1, transform.a, transform.e, transform.c, transform.f,
                       transform.b, transform.d, srid, w, h)
    flags = 10 | (0x40 if nodata is not None else 0)          # 10 = 32-bit float pixels
    nod = struct.pack("<f", nodata if nodata is not None else 0)
    return head + bytes([flags]) + nod + np.ascontiguousarray(band, dtype="<f4").tobytes()


@source("gsi_lidar_dsm")
def load_lidar():
    # NYU 2015 Dublin city LiDAR: four 1 m surface-model tiles (rooftops included), the only GSI LiDAR over the city.
    import rasterio
    from rasterio.windows import Window
    size = 100
    tiles = need(gsiLidarAPI.lidarTiles(), "GSI LiDAR tile index")
    with db.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS dsm; CREATE TABLE dsm(rid serial, rast raster)"))
        for t in tiles:
            path = cached(gsiLidarAPI.downloadTile, f"{t['DATA_NAME']}.zip", t["DATA_URL"])
            tif = next(n for n in zipfile.ZipFile(path).namelist() if n.endswith(".tif"))
            with rasterio.open(f"zip://{path}!{tif}") as src:
                band, nodata = src.read(1), src.nodata
                rows = []
                for r0 in range(0, src.height, size):
                    for c0 in range(0, src.width, size):
                        win = Window(c0, r0, min(size, src.width - c0), min(size, src.height - r0))
                        block = band[r0:r0 + win.height, c0:c0 + win.width]
                        rows.append({"b": raster_wkb(block, src.window_transform(win), ITM, nodata)})
            c.execute(text("INSERT INTO dsm(rast) VALUES (ST_RastFromWKB(:b))"), rows)
        c.execute(text("CREATE INDEX ON dsm USING gist (ST_ConvexHull(rast))"))
        n = c.execute(text("SELECT count(*) FROM dsm")).scalar()
    return f"{n} raster tiles from {len(tiles)} NYU LiDAR tiles -> dsm"


@source("osm_infrastructure")
def load_osm():
    rows = []
    for el in need(osmAPI.infrastructureQuery(S, W, N, E), "Overpass"):
        tags = el.get("tags", {})
        if el["type"] == "node":
            geom = Point(el["lon"], el["lat"])
        elif "geometry" in el and len(el["geometry"]) > 1:
            pts = [(p["lon"], p["lat"]) for p in el["geometry"]]
            closed = pts[0] == pts[-1] and len(pts) > 3 and "highway" not in tags
            geom = Polygon(pts) if closed else LineString(pts)
        else:
            continue
        kind = ("critical" if tags.get("amenity") or tags.get("power") else
                "bridge" if tags.get("bridge") else "road" if "highway" in tags else
                "rail" if "railway" in tags else "building")
        rows.append({"osm_id": f"{el['type'][0]}{el['id']}", "kind": kind, "name": tags.get("name"),
                     "tags": json.dumps(tags), "geometry": geom})
    return to_db(gpd.GeoDataFrame(rows, crs=4326), "infrastructure")


@source("cso_small_areas")
def load_small_areas():
    gdf = gpd.read_file(io.BytesIO(need(csoAPI.smallAreaBoundaries(), "CSO small areas")))
    return to_db(gdf[gdf.intersects(DUBLIN.to_crs(gdf.crs)[0])], "small_areas")


@source("cso_saps_population")
def load_saps():
    df = pd.read_csv(io.BytesIO(need(csoAPI.smallAreaPopulation(), "CSO SAPS")), low_memory=False)
    df.to_sql("saps", db, if_exists="replace", index=False)
    return f"{len(df)} small areas -> saps"


# ---------------- Kafka -> detector -> readings ----------------

@source("kafka_to_readings")
def detect():
    """The flood detector: consume flood.readings and store each reading for the flood check."""
    if os.getenv("SIM_LEVEL"):  # a simulated Dublin Port reading, to test what a flood looks like
        publish_reading("simulated", "Dublin Port", float(os.environ["SIM_LEVEL"]), dt.datetime.now(dt.timezone.utc))
    if not USE_KAFKA:
        return "skipped (SKIP_KAFKA=1), readings were written straight to the database"
    if not published:
        return "nothing to stream (OPW and tide feeds returned no readings)"
    left = _producer.flush(30)
    if left:
        raise RuntimeError(f"{left} readings could not be delivered to Kafka at {KAFKA}")
    from confluent_kafka import Consumer
    consumer = Consumer(kafka_config(**{"group.id": os.getenv("KAFKA_GROUP", "flood-detector"), "auto.offset.reset": "earliest"}))
    consumer.subscribe([KAFKA_TOPIC])
    waiting, deadline = set(published), time.time() + 60
    while waiting and time.time() < deadline:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        r = json.loads(msg.value())
        save_reading(r["source"], r["station"], r["level_m"], r["time"])
        waiting.discard(r.get("id"))
    consumer.close()
    if waiting:
        raise RuntimeError(f"{len(waiting)} of {len(published)} readings did not come back from Kafka topic {KAFKA_TOPIC} within 60 s")
    return f"{len(published)} readings via Kafka {KAFKA_TOPIC} -> readings"


# ---------------- the check ----------------

def flood_check():
    """Returns False when the check could not run because a needed layer or reading is missing."""
    with db.connect() as c:
        missing = [t for t in ("cfram_nodes", "flood_extent_coast")
                   if not c.execute(text("SELECT to_regclass(:t) IS NOT NULL"), dict(t=t)).scalar()]
        if missing:
            print(f"\nFlood check skipped: {', '.join(missing)} did not load (see FAIL lines above).")
            return False
        lvl = c.execute(text("SELECT level_m, source FROM readings WHERE station='Dublin Port' AND (source <> 'simulated' OR :sim)"
                             " ORDER BY time DESC LIMIT 1"), dict(sim=bool(os.getenv("SIM_LEVEL")))).first()
        node = c.execute(text("""SELECT "WL_10PC", "WL_05PC", "WL_01PC" FROM cfram_nodes
            WHERE "WL_10PC" > 0 ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 2157) LIMIT 1"""),
            dict(x=DUBLIN_PORT.x, y=DUBLIN_PORT.y)).first()
        if lvl is None or node is None:
            print("\nFlood check skipped: no Dublin Port reading yet (marine_tide_gauges failed?). Set SIM_LEVEL to test.")
            return False
        print(f"\nDublin Port {lvl.level_m:.2f} m ({lvl.source}); CFRAM node 10% {node.WL_10PC:.2f} / 0.5% {node.WL_05PC:.2f} / 0.1% {node.WL_01PC:.2f}")
        band = next((b for b, wl in (("0.1%", node.WL_01PC), ("0.5%", node.WL_05PC), ("10%", node.WL_10PC)) if lvl.level_m >= wl), None)
        if not band:
            print("Below the 10% AEP level: no flood extent active.")
            return True
        if not c.execute(text("SELECT to_regclass('infrastructure') IS NOT NULL")).scalar():
            print(f"{band} AEP coastal extent is active, but no infrastructure layer is loaded.")
            return False
        has_dsm = c.execute(text("SELECT to_regclass('dsm') IS NOT NULL")).scalar()
        depth = """(SELECT :lvl - max(ST_Value(d.rast, ST_PointOnSurface(i.geometry))) FROM dsm d
                    WHERE ST_Intersects(d.rast, ST_PointOnSurface(i.geometry)))""" if has_dsm else "NULL"
        rows = c.execute(text(f"""
            WITH zone AS (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep = :band)
            SELECT i.kind, coalesce(i.name, i.osm_id) AS name, {depth} AS depth
            FROM infrastructure i, zone WHERE ST_Intersects(i.geometry, zone.g)
            ORDER BY i.kind, name"""), dict(band=band, lvl=lvl.level_m)).all()
        people = c.execute(text("""SELECT count(*) FROM small_areas s, (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep=:band) z
                                   WHERE ST_Intersects(s.geometry, z.g)"""), dict(band=band)).scalar() \
            if c.execute(text("SELECT to_regclass('small_areas') IS NOT NULL")).scalar() else "n/a"
    grade = lambda k, d: "unsafe" if d is None else ("safe" if d < (0.10 if k == "road" else 0) else
                                                     "caution" if d < (0.30 if k == "road" else 0.15) else "unsafe")
    print(f"Active band: {band} AEP coastal extent. {len(rows)} assets inside, {people} CSO small areas touched.")
    for r in rows:
        d = f"{r.depth:.2f} m" if r.depth is not None else "depth n/a"
        print(f"  {grade(r.kind, r.depth):<8}{r.kind:<9}{r.name}  ({d})")
    return True


if __name__ == "__main__":
    setup_db()
    for load in (load_opw, load_tides, load_warnings, load_forecast, load_gtfs, load_gtfsr,
                 load_nodes, load_river, load_coast, load_icwws, load_lidar, load_osm,
                 load_small_areas, load_saps, detect):
        load()
    failed = [n for n, s in status.items() if s.startswith("FAIL")]
    if failed:
        print(f"\n{len(failed)} of {len(status)} sources failed: {', '.join(failed)}")
    sys.exit(0 if flood_check() else 1)
