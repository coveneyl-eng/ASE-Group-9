"""Public Transport Agent: extra capacity for an event, using the OSM road layer loaded by osm2pgsql."""
from smartcity.agents.base import Agent
from smartcity.models import EventPlan, TransportPlan

agent = Agent("public-transport")

NEARBY_ROADS_SQL = """
SELECT name FROM osm_line
 WHERE highway IS NOT NULL
   AND ST_DWithin(ST_Transform(way, 4326)::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 1500)
 ORDER BY ST_Distance(ST_Transform(way, 4326)::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
 LIMIT 3
"""


def handle(topic: str, plan: EventPlan) -> None:
    roads = [r["name"] for r in agent.db.execute(NEARBY_ROADS_SQL, (plan.lon, plan.lat, plan.lon, plan.lat))]
    buses = max(plan.expected_attendance // 1500, 1)  # ~ one double-decker shuttle loop per 1,500 people
    tp = TransportPlan(trace_id=plan.trace_id, event_id=plan.event_id, extra_buses=buses, routes=roads)
    agent.publisher.publish("event.transport", tp)
    agent.decide(plan.trace_id, tp.model_dump(mode="json"))
    agent.log.info("event %s: +%d buses via %s", plan.event_name, buses, roads)


if __name__ == "__main__":
    agent.run(["event.plans"], handle)
