"""Hello-world thin slice: load every flood data source for Dublin city, pass one
water level reading through MQTT -> Kafka, then list infrastructure in the flood zone.

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
    MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, MQTT_TLS=1
    SKIP_SENSOR_HOP=1 skip the MQTT -> Kafka step (when no broker is deployed)
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
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
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


def mqtt_client(mqtt):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
    if os.getenv("MQTT_TLS") == "1":
        client.tls_set()
    client.connect(MQTT_HOST, MQTT_PORT)
    return client

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
        save_reading("opw", f"{r.station_ref}_{r.sensor_ref}", float(r.value), r.datetime)
    return to_db(gdf, "opw_latest")


@source("marine_tide_gauges")
def load_tides():
    t = need(marineTideAPI.tideGaugeReadings("Dublin Port|Howth.*", hours=2), "Marine Institute tide gauges")
    df = pd.DataFrame(t["rows"], columns=t["columnNames"])
    df = df[df.QC_Flag.astype(str) != "9"]  # 9 = missing; live rows are 0 (not yet QC'd), 1 = good
    for r in df.itertuples():
        save_reading("marine", r.station_id, float(r.Water_Level_OD_Malin), r.time)
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


TILE = 100  # raster tile size in pixels, as ST_Tile(..., 100, 100) did before

# numpy dtype -> PostGIS raster pixel type code
PIXTYPE = {"uint8": 4, "int8": 3, "int16": 5, "uint16": 6, "int32": 7, "uint32": 8, "float32": 10, "float64": 11}


def raster_wkb(block, transform, x0, y0, nodata, srid):
    """One (bands, rows, cols) numpy block, offset (x0, y0) pixels into a raster with this affine transform,
    encoded in PostGIS raster WKB (little endian), ready for ST_RastFromWKB."""
    import struct
    import numpy as np
    bands, h, w = block.shape
    a, b, c0, d, e, f0 = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    out = [struct.pack("<BHHddddddiHH", 1, 0, bands,  # endian, version, bands, scale x/y, origin x/y, skew x/y, srid, w, h
                       a, e, c0 + x0 * a + y0 * b, f0 + x0 * d + y0 * e, b, d, srid, w, h)]
    dtype = np.dtype(block.dtype).newbyteorder("<")
    for band in block:
        flags = PIXTYPE[block.dtype.name] | (0x40 if nodata is not None else 0)
        out.append(struct.pack("<B", flags))
        out.append(np.array(nodata if nodata is not None else 0, dtype=dtype).tobytes())
        out.append(np.ascontiguousarray(band, dtype=dtype).tobytes())
    return b"".join(out)


@source("gsi_lidar_dsm")
def load_lidar():
    # NYU 2015 Dublin city LiDAR: four 1 m surface-model tiles (rooftops included), the only GSI LiDAR over the city.
    import rasterio
    # Tiles are built here as PostGIS raster WKB, so the database needs no GDAL drivers
    # (Azure's managed Postgres refuses SET postgis.gdal_enabled_drivers).
    from rasterio.windows import Window
    tiles = need(gsiLidarAPI.lidarTiles(), "GSI LiDAR tile index")
    with db.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS dsm; CREATE TABLE dsm(rid serial, rast raster)"))
        for t in tiles:
            path = cached(gsiLidarAPI.downloadTile, f"{t['DATA_NAME']}.zip", t["DATA_URL"])
            tif = next(n for n in zipfile.ZipFile(path).namelist() if n.endswith(".tif"))
            with rasterio.open(f"zip://{path}!{tif}") as src:
                for y0 in range(0, src.height, TILE):  # one strip of tiles at a time keeps memory low
                    strip = src.read(window=Window(0, y0, src.width, min(TILE, src.height - y0)))
                    c.execute(text("INSERT INTO dsm(rast) VALUES (ST_RastFromWKB(:b))"),
                              [{"b": raster_wkb(strip[:, :, x0:x0 + TILE], src.transform, x0, y0, src.nodata, ITM)}
                               for x0 in range(0, src.width, TILE)])
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


# ---------------- one reading through MQTT -> Kafka ----------------

@source("mqtt_to_kafka")
def sensor_hop():
    import paho.mqtt.client as mqtt
    from confluent_kafka import Producer, Consumer

    with db.connect() as c:  # latest real Dublin Port level, unless SIM_LEVEL forces a simulated one
        live = c.execute(text("SELECT time, level_m FROM readings WHERE station='Dublin Port' AND source='marine' ORDER BY time DESC LIMIT 1")).first()
    sim = os.getenv("SIM_LEVEL") or (None if live else "2.80")
    reading = {"id": str(uuid.uuid4()), "station": "Dublin Port", "level_m": float(sim) if sim else live.level_m,
               "time": dt.datetime.now(dt.timezone.utc).isoformat() if sim else live.time.isoformat(),
               "source": "simulated" if sim else "marine"}

    if os.getenv("SKIP_SENSOR_HOP") == "1":
        return "skipped (SKIP_SENSOR_HOP=1)"
    producer = Producer(kafka_config())
    got = []
    sub = mqtt_client(mqtt)  # edge gateway: MQTT -> Kafka bridge
    sub.on_message = lambda c, u, m: (producer.produce(KAFKA_TOPIC, m.payload), producer.flush(10), got.append(1))
    sub.subscribe("sensors/dublin-port/level", qos=1); sub.loop_start()
    time.sleep(0.5)
    pub = mqtt_client(mqtt)  # the field sensor
    pub.loop_start()
    pub.publish("sensors/dublin-port/level", json.dumps(reading), qos=1).wait_for_publish(timeout=10)
    pub.loop_stop()
    for _ in range(50):
        if got: break
        time.sleep(0.1)
    sub.loop_stop()

    if not got:
        raise RuntimeError(f"the reading never came back from MQTT at {MQTT_HOST}:{MQTT_PORT}")
    consumer = Consumer(kafka_config(**{"group.id": os.getenv("KAFKA_GROUP", "flood-detector"), "auto.offset.reset": "earliest"}))
    consumer.subscribe([KAFKA_TOPIC])
    msg = None
    for _ in range(30):
        msg = consumer.poll(1.0)
        if msg and not msg.error() and json.loads(msg.value()).get("id") == reading["id"]:
            break
    consumer.close()
    if not msg or msg.error() or json.loads(msg.value()).get("id") != reading["id"]:
        raise RuntimeError(f"the reading did not arrive on Kafka topic {KAFKA_TOPIC} at {KAFKA} within 30 s")
    r = json.loads(msg.value())
    save_reading(r["source"], r["station"], r["level_m"], r["time"])
    return f"{r['station']} {r['level_m']} m OD Malin ({r['source']}) via MQTT -> Kafka -> readings"


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
                 load_small_areas, load_saps, sensor_hop):
        load()
    failed = [n for n, s in status.items() if s.startswith("FAIL")]
    if failed:
        print(f"\n{len(failed)} of {len(status)} sources failed: {', '.join(failed)}")
    sys.exit(0 if flood_check() else 1)
