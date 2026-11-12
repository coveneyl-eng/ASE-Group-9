"""Hello-world thin slice: load every flood data source for Dublin city, pass one
water level reading through MQTT -> Kafka, then list infrastructure in the flood zone.

    docker compose up -d
    pip install -r requirements.txt
    python load_all.py                  # NTA_API_KEY=... for GTFS-Realtime, SIM_LEVEL=2.9 to force a reading
"""
import io, json, os, time, uuid, zipfile, datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pandas as pd
import geopandas as gpd
from shapely.geometry import box, Point, LineString, Polygon
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DB_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
KAFKA = os.getenv("KAFKA", "localhost:9092")
CACHE = Path(os.getenv("CACHE", "data")); CACHE.mkdir(exist_ok=True)

W, S, E, N = -6.39, 53.29, -6.10, 53.42          # Dublin city, WGS84
ITM = 2157                                        # Irish Transverse Mercator, metres
DUBLIN = gpd.GeoSeries([box(W, S, E, N)], crs=4326)
DUBLIN_PORT = Point(-6.2217, 53.3457)             # Marine Institute tide gauge

OPW_S3 = "https://s3.eu-west-1.amazonaws.com/catalogue.floodinfo.opw"
URLS = {
    "opw_latest": "http://waterlevel.ie/geojson/latest/",
    "erddap": "https://erddap.marine.ie/erddap/tabledap/IrishNationalTideGaugeNetwork.json",
    "met_warnings": "https://www.met.ie/Open_Data/json/warning_IRELAND.json",
    "met_forecast": "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast?lat=53.35;long=-6.26",
    "gtfs_static": "https://www.transportforireland.ie/transitData/Data/GTFS_Dublin_Bus.zip",
    "gtfsr": "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates?format=json",
    "cfram_nodes": f"{OPW_S3}/cfram/esds_nodes_current.zip",
    "cfram_river": f"{OPW_S3}/cfram/esds_floodmap_ext_f_c.zip",
    "cfram_coast": f"{OPW_S3}/cfram/esds_floodmap_ext_c_c.zip",
    "icwws": "https://s3-eu-west-1.amazonaws.com/catalogue.floodinfo.opw/"
             "icwws-2018-phase1-national-coastal-extreme-water-level-estimation-points-itm-osgm15.csv",
    "lidar": "https://gsi.geodata.gov.ie/server/rest/services/Lidar/IE_GSI_LiDAR_Coverage_NYU_Dublin_IE26_ITM/FeatureServer/4/query",
    "overpass": "https://overpass-api.de/api/interpreter",
    "cso_ckan": "https://data.gov.ie/api/3/action/package_show?id="
                "cso-small-areas-national-statistical-boundaries-2022-generalised-20m",
    "cso_saps": "https://www.cso.ie/en/media/csoie/census/census2022/SAPS_2022_Small_Area_UR_171024.csv",
}

db = create_engine(DB_URL)
http = httpx.Client(timeout=float(os.getenv("HTTP_TIMEOUT", "180")), follow_redirects=True, headers={"User-Agent": "dublin-flood-thin-slice"})
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


def patient(method, url, tries=8, **kw):
    """Retry while the server says 'busy' or 'still generating' (Overpass 429/5xx, ArcGIS Hub 202)."""
    for i in range(tries):
        r = http.request(method, url, **kw)
        if r.status_code not in (202, 429, 502, 503, 504):
            return r.raise_for_status()
        time.sleep(min(5 * 2 ** i, 120))
    return r.raise_for_status()


def cached(url, name):
    path = CACHE / name
    if not path.exists():
        with http.stream("GET", url) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return path


def to_db(gdf, table):
    gdf.to_crs(ITM).to_postgis(table, db, if_exists="replace", index=False)
    return f"{len(gdf)} rows -> {table}"


def save_reading(source_name, station, level_m, t):
    with db.begin() as c:
        c.execute(text("INSERT INTO readings VALUES (:t, :s, :st, :v) ON CONFLICT DO NOTHING"),
                  dict(t=t, s=source_name, st=station, v=level_m))


def setup_db():
    with db.begin() as c:
        for ext in ("postgis", "postgis_raster", "timescaledb", "pgrouting"):
            c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext} CASCADE"))
        c.execute(text("""CREATE TABLE IF NOT EXISTS readings(
            time timestamptz NOT NULL, source text, station text, level_m double precision,
            PRIMARY KEY (time, source, station))"""))
        c.execute(text("SELECT create_hypertable('readings', 'time', if_not_exists => TRUE)"))


# ---------------- live feeds ----------------

@source("opw_waterlevel")
def load_opw():
    gdf = gpd.read_file(io.BytesIO(http.get(URLS["opw_latest"], params={"t": int(time.time())}).content))
    gdf = gdf.clip(DUBLIN.to_crs(gdf.crs))
    for r in gdf[gdf.value.notna()].itertuples():
        save_reading("opw", f"{r.station_ref}_{r.sensor_ref}", float(r.value), r.datetime)
    return to_db(gdf, "opw_latest")


@source("marine_tide_gauges")
def load_tides():
    q = 'time,station_id,latitude,longitude,Water_Level_OD_Malin,QC_Flag&station_id=~"Dublin Port|Howth.*"&time>=now-2hours'
    t = http.get(f"{URLS['erddap']}?{q}").json()["table"]
    df = pd.DataFrame(t["rows"], columns=t["columnNames"])
    df = df[df.QC_Flag.astype(str) != "9"]  # 9 = missing; live rows are 0 (not yet QC'd), 1 = good
    for r in df.itertuples():
        save_reading("marine", r.station_id, float(r.Water_Level_OD_Malin), r.time)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=4326)
    return to_db(gdf, "tide_readings")


@source("met_warnings")
def load_warnings():
    warnings = http.get(URLS["met_warnings"]).json()
    pd.DataFrame({"raw": [json.dumps(w) for w in warnings]}).to_sql("met_warnings", db, if_exists="replace", index=False)
    return f"{len(warnings)} active warnings -> met_warnings"


@source("met_point_forecast")
def load_forecast():
    root = ET.fromstring(http.get(URLS["met_forecast"]).content)
    rows = [(t.get("from"), t.get("to"), float(p.get("value")))
            for t in root.iter("time") for p in t.iter("precipitation")]
    pd.DataFrame(rows, columns=["from", "to", "precip_mm"]).to_sql("met_forecast", db, if_exists="replace", index=False)
    return f"{len(rows)} rainfall periods -> met_forecast"


@source("nta_gtfs_static")
def load_gtfs():
    z = zipfile.ZipFile(cached(URLS["gtfs_static"], "gtfs_dublin_bus.zip"))
    stops = pd.read_csv(z.open("stops.txt"))
    gdf = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), crs=4326).clip(DUBLIN)
    pd.read_csv(z.open("routes.txt")).to_sql("bus_routes", db, if_exists="replace", index=False)
    return to_db(gdf, "bus_stops")


@source("nta_gtfs_realtime")
def load_gtfsr():
    key = os.environ["NTA_API_KEY"]  # free key from developer.nationaltransport.ie
    feed = http.get(URLS["gtfsr"], headers={"x-api-key": key}).json()
    pd.DataFrame({"raw": [json.dumps(e) for e in feed["entity"]]}).to_sql("gtfsr_trip_updates", db, if_exists="replace", index=False)
    return f"{len(feed['entity'])} trip updates -> gtfsr_trip_updates"


# ---------------- static layers ----------------

@source("cfram_nodes")
def load_nodes():
    path = cached(URLS["cfram_nodes"], "cfram_nodes.zip")
    gdf = gpd.read_file(f"zip://{path}", bbox=DUBLIN)
    return to_db(gdf, "cfram_nodes")


def load_extents(key, table):
    path = cached(URLS[key], f"{key}.zip")
    parts = []
    for shp in [n for n in zipfile.ZipFile(path).namelist() if n.endswith(".shp")]:
        gdf = gpd.read_file(f"zip://{path}!{shp}", bbox=DUBLIN)
        gdf["aep"] = {"0010": "10%", "0100": "1%", "0200": "0.5%", "1000": "0.1%"}[shp[-8:-4]]
        parts.append(gdf[["aep", "geometry"]])
    return to_db(gpd.GeoDataFrame(pd.concat(parts), crs=parts[0].crs), table)


load_river = source("cfram_river_extents")(lambda: load_extents("cfram_river", "flood_extent_river"))
load_coast = source("cfram_coastal_extents")(lambda: load_extents("cfram_coast", "flood_extent_coast"))


@source("icwws_coastal_levels")
def load_icwws():
    df = pd.read_csv(cached(URLS["icwws"], "icwws.csv"))
    df.columns = [c.replace("%", "pc").replace("+", "plus").replace(".", "_") for c in df.columns]
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.Easting, df.Northing), crs=ITM)
    return to_db(gdf.clip(DUBLIN.to_crs(ITM)), "icwws_points")


@source("gsi_lidar_dsm")
def load_lidar():
    # NYU 2015 Dublin city LiDAR: four 1 m surface-model tiles (rooftops included), the only GSI LiDAR over the city.
    import rasterio
    tiles = http.get(URLS["lidar"], params=dict(where="1=1", outFields="DATA_URL,DATA_NAME",
                                                returnGeometry="false", f="json")).json()["features"]
    with db.begin() as c:
        c.execute(text("SET postgis.gdal_enabled_drivers = 'GTiff'"))
        c.execute(text("DROP TABLE IF EXISTS dsm; CREATE TABLE dsm(rid serial, rast raster)"))
        for t in tiles:
            path = cached(t["attributes"]["DATA_URL"], f"{t['attributes']['DATA_NAME']}.zip")
            tif = next(n for n in zipfile.ZipFile(path).namelist() if n.endswith(".tif"))
            with rasterio.open(f"zip://{path}!{tif}") as src, rasterio.MemoryFile() as mem:
                with mem.open(**{**src.profile, "driver": "GTiff", "crs": "EPSG:2157"}) as dst:
                    dst.write(src.read())
                c.execute(text("INSERT INTO dsm(rast) SELECT ST_Tile(ST_FromGDALRaster(:b, 2157), 100, 100)"),
                          {"b": bytes(mem.getbuffer())})
        c.execute(text("CREATE INDEX ON dsm USING gist (ST_ConvexHull(rast))"))
        n = c.execute(text("SELECT count(*) FROM dsm")).scalar()
    return f"{n} raster tiles from {len(tiles)} NYU LiDAR tiles -> dsm"


@source("osm_infrastructure")
def load_osm():
    q = f"""[out:json][timeout:300];
    ( way["highway"]({S},{W},{N},{E}); way["building"]({S},{W},{N},{E}); way["railway"~"rail|light_rail"]({S},{W},{N},{E});
      nwr["amenity"~"hospital|clinic|school|fire_station|police"]({S},{W},{N},{E}); nwr["power"="substation"]({S},{W},{N},{E}); );
    out tags geom;"""
    rows = []
    for el in patient("POST", URLS["overpass"], data={"data": q}, timeout=360).json()["elements"]:
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
    res = http.get(URLS["cso_ckan"]).json()["result"]["resources"]
    url = next(r["url"] for r in res if r["format"].lower() in ("geojson", "json"))
    gdf = gpd.read_file(io.BytesIO(patient("GET", url).content))
    return to_db(gdf[gdf.intersects(DUBLIN.to_crs(gdf.crs)[0])], "small_areas")


@source("cso_saps_population")
def load_saps():
    df = pd.read_csv(io.BytesIO(http.get(URLS["cso_saps"]).content), low_memory=False)
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

    producer = Producer({"bootstrap.servers": KAFKA})
    got = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # edge gateway: MQTT -> Kafka bridge
    sub.on_message = lambda c, u, m: (producer.produce("flood.readings", m.payload), producer.flush(), got.append(1))
    sub.connect(MQTT_HOST); sub.subscribe("sensors/dublin-port/level", qos=1); sub.loop_start()
    time.sleep(0.5)
    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # the field sensor
    pub.connect(MQTT_HOST); pub.loop_start()
    pub.publish("sensors/dublin-port/level", json.dumps(reading), qos=1).wait_for_publish(timeout=10)
    pub.loop_stop()
    for _ in range(50):
        if got: break
        time.sleep(0.1)
    sub.loop_stop()

    consumer = Consumer({"bootstrap.servers": KAFKA, "group.id": f"flood-detector-{uuid.uuid4()}", "auto.offset.reset": "earliest"})
    consumer.subscribe(["flood.readings"])
    msg = None
    for _ in range(30):
        msg = consumer.poll(1.0)
        if msg and not msg.error() and json.loads(msg.value()).get("id") == reading["id"]:
            break
    consumer.close()
    r = json.loads(msg.value())
    save_reading(r["source"], r["station"], r["level_m"], r["time"])
    return f"{r['station']} {r['level_m']} m OD Malin ({r['source']}) via MQTT -> Kafka -> readings"


# ---------------- the check ----------------

def flood_check():
    with db.connect() as c:
        lvl = c.execute(text("SELECT level_m, source FROM readings WHERE station='Dublin Port' AND (source <> 'simulated' OR :sim)"
                             " ORDER BY time DESC LIMIT 1"), dict(sim=bool(os.getenv("SIM_LEVEL")))).first()
        node = c.execute(text("""SELECT "WL_10PC", "WL_05PC", "WL_01PC" FROM cfram_nodes
            WHERE "WL_10PC" > 0 ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 2157) LIMIT 1"""),
            dict(x=DUBLIN_PORT.x, y=DUBLIN_PORT.y)).first()
        print(f"\nDublin Port {lvl.level_m:.2f} m ({lvl.source}); CFRAM node 10% {node.WL_10PC:.2f} / 0.5% {node.WL_05PC:.2f} / 0.1% {node.WL_01PC:.2f}")
        band = next((b for b, wl in (("0.1%", node.WL_01PC), ("0.5%", node.WL_05PC), ("10%", node.WL_10PC)) if lvl.level_m >= wl), None)
        if not band:
            print("Below the 10% AEP level: no flood extent active.")
            return
        if not c.execute(text("SELECT to_regclass('infrastructure') IS NOT NULL")).scalar():
            print(f"{band} AEP coastal extent is active, but no infrastructure layer is loaded.")
            return
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


if __name__ == "__main__":
    setup_db()
    for load in (load_opw, load_tides, load_warnings, load_forecast, load_gtfs, load_gtfsr,
                 load_nodes, load_river, load_coast, load_icwws, load_lidar, load_osm,
                 load_small_areas, load_saps, sensor_hop):
        load()
    flood_check()
