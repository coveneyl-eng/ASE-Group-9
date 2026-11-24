"""The flood check from flood-thin-slice/load_all.py (flood_check), returning data instead of printing it.

Same band order, same SQL, same safe / caution / unsafe grading, so the dashboard and load_all.py always agree.
Tables are the ones load_all.py writes (all geometry in Irish Transverse Mercator, EPSG:2157).
"""
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import Engine

DUBLIN_PORT = (-6.2217, 53.3457)  # Marine Institute tide gauge (lon, lat)
MAX_ASSETS = 400  # assets returned for the map/list; counts always cover all of them


def band_for(level_m: float, wl_10: float, wl_05: float, wl_01: float) -> str | None:
    """Highest CFRAM annual-exceedance band the level reaches (same order as load_all.flood_check)."""
    for band, wl in (("0.1%", wl_01), ("0.5%", wl_05), ("10%", wl_10)):
        if level_m >= wl:
            return band
    return None


def grade(kind: str, depth: float | None) -> str:
    """load_all.flood_check's grading: roads tolerate more water than buildings; unknown depth is unsafe."""
    if depth is None:
        return "unsafe"
    if depth < (0.10 if kind == "road" else 0):
        return "safe"
    return "caution" if depth < (0.30 if kind == "road" else 0.15) else "unsafe"


def exists(c, table: str) -> bool:
    return bool(c.execute(text("SELECT to_regclass(:t) IS NOT NULL"), dict(t=table)).scalar())


def latest_level(c) -> dict | None:
    """Latest real (not simulated) Dublin Port reading, as load_all uses it."""
    if not exists(c, "readings"):
        return None
    r = c.execute(text("SELECT level_m, source, time FROM readings WHERE station = 'Dublin Port' "
                       "AND source <> 'simulated' ORDER BY time DESC LIMIT 1")).first()
    return None if r is None else {"value": r.level_m, "source": r.source, "time": r.time.isoformat(),
                                   "simulated": False}


def nearest_node(c) -> dict | None:
    r = c.execute(text("""SELECT "WL_10PC", "WL_05PC", "WL_01PC" FROM cfram_nodes WHERE "WL_10PC" > 0
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 4326), 2157) LIMIT 1"""),
                  dict(x=DUBLIN_PORT[0], y=DUBLIN_PORT[1])).first()
    return None if r is None else {"wl_10": r.WL_10PC, "wl_05": r.WL_05PC, "wl_01": r.WL_01PC}


@lru_cache(maxsize=8)
def extent_geojson(engine: Engine, band: str) -> dict | None:
    """The active coastal extent, simplified to ~5 m and in WGS84 for the map (static layer, so cached)."""
    with engine.connect() as c:
        g = c.execute(text("""SELECT ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(ST_Union(geometry), 5), 4326), 6)
                              FROM flood_extent_coast WHERE aep = :band"""), dict(band=band)).scalar()
    import json
    return json.loads(g) if g else None


def check(engine: Engine, level_override: float | None = None) -> dict:
    """Run the flood check against the latest Dublin Port reading, or a what-if level from the dashboard."""
    with engine.connect() as c:
        missing = [t for t in ("cfram_nodes", "flood_extent_coast") if not exists(c, t)]
        if missing:
            return {"status": "skipped", "reason": f"{', '.join(missing)} not loaded yet: run load_all.py"}
        level = ({"value": level_override, "source": "simulated", "time": None, "simulated": True}
                 if level_override is not None else latest_level(c))
        node = nearest_node(c)
        if level is None or node is None:
            return {"status": "skipped", "reason": "no Dublin Port reading yet (marine_tide_gauges failed?)",
                    "node": node}
        band = band_for(level["value"], node["wl_10"], node["wl_05"], node["wl_01"])
        result = {"status": "ok", "level": level, "node": node, "band": band}
        if not band:
            return {**result, "assets": {"total": 0, "by_grade": {}, "by_kind": {}, "items": []},
                    "small_areas_touched": 0, "extent": None}
        if not exists(c, "infrastructure"):
            return {**result, "status": "partial", "reason": "infrastructure layer not loaded"}
        depth = """(SELECT :lvl - max(ST_Value(d.rast, ST_PointOnSurface(i.geometry))) FROM dsm d
                    WHERE ST_Intersects(d.rast, ST_PointOnSurface(i.geometry)))""" if exists(c, "dsm") else "NULL"
        rows = c.execute(text(f"""
            WITH zone AS (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep = :band)
            SELECT i.kind, coalesce(i.name, i.osm_id) AS name, {depth} AS depth,
                   ST_X(ST_Transform(ST_PointOnSurface(i.geometry), 4326)) AS lon,
                   ST_Y(ST_Transform(ST_PointOnSurface(i.geometry), 4326)) AS lat
            FROM infrastructure i, zone WHERE ST_Intersects(i.geometry, zone.g)
            ORDER BY i.kind, name"""), dict(band=band, lvl=level["value"])).all()
        people = c.execute(text("""SELECT count(*) FROM small_areas s,
                (SELECT ST_Union(geometry) g FROM flood_extent_coast WHERE aep = :band) z
                WHERE ST_Intersects(s.geometry, z.g)"""), dict(band=band)).scalar() \
            if exists(c, "small_areas") else None
    items = [{"kind": r.kind, "name": r.name, "depth": None if r.depth is None else round(r.depth, 2),
              "grade": grade(r.kind, r.depth), "lon": r.lon, "lat": r.lat} for r in rows]
    by_grade, by_kind = {}, {}
    for i in items:
        by_grade[i["grade"]] = by_grade.get(i["grade"], 0) + 1
        by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
    order = {"unsafe": 0, "caution": 1, "safe": 2}
    items.sort(key=lambda i: (order[i["grade"]], i["kind"], str(i["name"])))
    return {**result, "assets": {"total": len(items), "by_grade": by_grade, "by_kind": by_kind,
                                 "items": items[:MAX_ASSETS]},
            "small_areas_touched": people, "extent": extent_geojson(engine, band)}
