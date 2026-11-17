"""Event Coordinating Agent: crowd/traffic plan per event, restricting venue access when a flood extent covers it."""
import json

from smartcity.agents.base import Agent
from smartcity.models import EventPlan, FloodImpact, UpcomingEvent

agent = Agent("event-coordinating")
latest_extent: dict | None = None

VENUE_FLOODED_SQL = """
SELECT ST_DWithin(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                  ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography, 300) AS near
"""


def handle(topic: str, msg) -> None:
    global latest_extent
    if isinstance(msg, FloodImpact):
        latest_extent = msg.extent_geojson
        return
    e: UpcomingEvent = msg
    restricted = bool(latest_extent) and agent.db.execute(
        VENUE_FLOODED_SQL, (e.lon, e.lat, json.dumps(latest_extent))).fetchone()["near"]
    cars = int(e.expected_attendance * 0.18)  # placeholder modal split, refined in iteration 5
    plan = EventPlan(trace_id=e.trace_id, event_id=e.id, event_name=e.event_name, lon=e.lon, lat=e.lat,
                     expected_attendance=e.expected_attendance, predicted_extra_cars=cars,
                     venue_access="restricted" if restricted else "open",
                     crowd_plan=f"{max(e.expected_attendance // 2500, 1)} Garda posts; stagger exits over 30 min")
    agent.publisher.publish("event.plans", plan)
    agent.decide(e.trace_id, plan.model_dump(mode="json"))
    agent.log.info("plan for %s: access=%s cars=%d", e.event_name, plan.venue_access, cars)


if __name__ == "__main__":
    agent.run(["event.watch", "flood.impacts"], handle)
