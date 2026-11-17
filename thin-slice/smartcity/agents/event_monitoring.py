"""Event Monitoring Agent: keeps the calendar of upcoming events and forwards those inside the planning lead time."""
from datetime import timedelta

from smartcity.agents.base import Agent
from smartcity.models import UpcomingEvent, now

agent = Agent("event-monitoring")
LEAD_TIME = timedelta(days=14)
seen: set[tuple[str, str]] = set()


def handle(topic: str, e: UpcomingEvent) -> None:
    key = (e.event_name, e.starts_at.isoformat())
    if key in seen or e.starts_at - now() > LEAD_TIME:
        return
    seen.add(key)
    agent.publisher.publish("event.watch", e)
    agent.decide(e.trace_id, {"watching": e.event_name, "venue": e.venue, "attendance": e.expected_attendance})
    agent.log.info("watching %s at %s (%d people)", e.event_name, e.venue, e.expected_attendance)


if __name__ == "__main__":
    agent.run(["event.upcoming"], handle)
