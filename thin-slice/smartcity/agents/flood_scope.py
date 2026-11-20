"""Flood Scope Agent: builds the flood extent (CFRAM layer or buffered gauge) and grades each asset in PostGIS."""
from uuid import uuid4

from smartcity.agents.base import Agent
from smartcity.models import AssetImpact, FloodEvent, FloodImpact

agent = Agent("flood-scope")

# One PostGIS query does the spatial overlay (KISS: let the database do spatial work).
IMPACT_SQL = """
WITH ext AS (
    SELECT COALESCE(
        (SELECT ST_Union(geom) FROM cfram_extents
          WHERE gauge_id = %(sensor)s AND trigger_level_m <= %(level)s),
        ST_Buffer(ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
                  150 + 300 * GREATEST(%(level)s - %(threshold)s, 0))::geometry
    ) AS geom
)
SELECT a.asset_id, a.name, a.kind,
       CASE WHEN ST_Intersects(a.geom, ext.geom) AND COALESCE(a.elevation_m, 0) < %(level)s THEN 'unsafe'
            WHEN ST_DWithin(a.geom::geography, ext.geom::geography, 150) THEN 'caution'
            ELSE 'safe' END AS status,
       ST_AsGeoJSON(ext.geom)::json AS extent
FROM assets a, ext
ORDER BY a.asset_id
"""


def handle(topic: str, e: FloodEvent) -> None:
    rows = agent.db.execute(IMPACT_SQL, {"sensor": e.sensor_id, "level": e.level_m, "threshold": e.threshold_m,
                                         "lon": e.lon, "lat": e.lat}).fetchall()
    impact_id = uuid4().hex
    impacts = [AssetImpact(asset_id=r["asset_id"], name=r["name"], kind=r["kind"], status=r["status"]) for r in rows]
    with agent.db.cursor() as cur:
        cur.executemany("INSERT INTO impacts (time, impact_id, event_id, asset_id, status) VALUES (now(), %s, %s, %s, %s)",
                        [(impact_id, e.id, i.asset_id, i.status) for i in impacts])
    msg = FloodImpact(id=impact_id, trace_id=e.trace_id, event_id=e.id, sensor_id=e.sensor_id,
                      extent_geojson=rows[0]["extent"], impacts=impacts, observed_at=e.observed_at)
    agent.publisher.publish("flood.impacts", msg)
    summary = {i.name: i.status for i in impacts}
    agent.decide(e.trace_id, {"impact_id": impact_id, "assets": summary})
    agent.log.info("impact %s: %s", impact_id, summary)


if __name__ == "__main__":
    agent.run(["flood.events"], handle)
