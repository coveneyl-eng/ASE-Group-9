"""Traffic Monitoring Agent: flags congested junctions from TomTom flow readings (APIs/trafficCongestionAPI)."""
from smartcity.agents.base import Agent
from smartcity.models import TrafficFlow

agent = Agent("traffic-monitoring")
CONGESTED = {"heavy", "standstill"}


def handle(topic: str, f: TrafficFlow) -> None:
    if f.level not in CONGESTED:
        return
    agent.publisher.publish("traffic.congestion", f)
    agent.decide(f.trace_id, {"junction": f.junction_id, "speed_ratio": f.speed_ratio, "level": f.level})
    agent.log.info("congestion at %s (%s, speed ratio %.2f)", f.junction_id, f.level, f.speed_ratio)


if __name__ == "__main__":
    agent.run(["traffic.flow"], handle)
