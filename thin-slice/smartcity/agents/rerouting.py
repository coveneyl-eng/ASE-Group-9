"""Rerouting Agent: pgRouting shortest path that avoids road edges inside the unsafe flood extent."""
import json

import httpx

from smartcity import lights
from smartcity.agents.base import Agent
from smartcity.models import FloodImpact, RerouteCommand

agent = Agent("rerouting")
BUS_FROM, BUS_TO = 3, 7  # sample bus corridor; its normal route crosses the flood-prone junction (node 4)

FLOODED_EDGES_SQL = """
SELECT array_agg(id ORDER BY id) AS ids FROM road_edges
 WHERE ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
"""
CENTRE_SQL = """
SELECT ST_Y(c) AS lat, ST_X(c) AS lon FROM ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)) AS c
"""
ROUTE_SQL = """
SELECT array_agg(edge ORDER BY seq) FILTER (WHERE edge > 0) AS edges, max(agg_cost) AS cost
  FROM pgr_dijkstra(
    format('SELECT id, source, target,
                   CASE WHEN id = ANY(%%L::int[]) THEN -1 ELSE cost END AS cost,
                   CASE WHEN id = ANY(%%L::int[]) THEN -1 ELSE reverse_cost END AS reverse_cost
              FROM road_edges', %(avoid)s::text, %(avoid)s::text),
    %(src)s, %(dst)s, directed => false)
"""


def handle(topic: str, impact: FloodImpact) -> None:
    flooded = agent.db.execute(FLOODED_EDGES_SQL, (json.dumps(impact.extent_geojson),)).fetchone()["ids"] or []
    avoid = "{" + ",".join(map(str, flooded)) + "}"
    route = agent.db.execute(ROUTE_SQL, {"avoid": avoid, "src": BUS_FROM, "dst": BUS_TO}).fetchone()
    closed = []
    try:  # hold the lights at the flooded junction red so traffic is not sent into the water
        centre = agent.db.execute(CENTRE_SQL, (json.dumps(impact.extent_geojson),)).fetchone()
        closed = [l["site_id"] for l in lights.nearest(centre["lat"], centre["lon"], radius_m=300)]
        if closed:
            lights.hold(closed, "red", 900)
    except httpx.HTTPError as exc:
        agent.log.warning("traffic-light API unreachable, reroute kept on Kafka only: %s", exc)
    cmd = RerouteCommand(trace_id=impact.trace_id, impact_id=impact.id, from_node=BUS_FROM, to_node=BUS_TO,
                         path_edges=route["edges"] or [], avoided_edges=flooded, total_cost=route["cost"] or -1,
                         closed_light_sites=closed)
    agent.publisher.publish("traffic.reroute", cmd)
    agent.decide(impact.trace_id, {"avoided": flooded, "path": cmd.path_edges, "cost_m": cmd.total_cost,
                                   "lights_red": closed})
    agent.log.info("reroute %s->%s via edges %s avoiding %s", BUS_FROM, BUS_TO, cmd.path_edges, flooded)


if __name__ == "__main__":
    agent.run(["flood.impacts"], handle)
