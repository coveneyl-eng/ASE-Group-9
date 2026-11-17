"""Traffic Control Agent: extends green time at the lights nearest a congested junction (trafficControlAPI)."""
import httpx

from smartcity import lights
from smartcity.agents.base import Agent
from smartcity.models import SignalCommand, TrafficFlow

agent = Agent("traffic-control")


def green_time(speed_ratio: float) -> int:
    """Placeholder optimiser: slower traffic gets longer green, bounded so pedestrians still get a phase."""
    return int(min(90, max(20, 20 + (1 - speed_ratio) * 80)))


def handle(topic: str, f: TrafficFlow) -> None:
    seconds = green_time(f.speed_ratio)
    try:
        sites = [l["site_id"] for l in lights.nearest(f.lat, f.lon)]
        if sites:
            lights.hold(sites, "green", seconds)
    except httpx.HTTPError as exc:
        agent.log.warning("traffic-light API unreachable, command kept on Kafka only: %s", exc)
        sites = []
    cmd = SignalCommand(trace_id=f.trace_id, junction_id=f.junction_id, site_ids=sites, state="green", seconds=seconds)
    agent.publisher.publish("traffic.signals", cmd)
    agent.decide(f.trace_id, cmd.model_dump(mode="json"))
    agent.log.info("%s: lights %s green for %ss", f.junction_id, sites, seconds)


if __name__ == "__main__":
    agent.run(["traffic.congestion"], handle)
