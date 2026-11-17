"""Shared agent plumbing: telemetry, Kafka publisher, DB connection and the decision log."""
import json
from functools import cached_property

from smartcity import bus, db, telemetry


class Agent:
    def __init__(self, name: str):
        self.name = name
        self.t = telemetry.setup(name)
        self.log = self.t["log"]

    # Connections open lazily so modules can be imported by unit tests without a running stack.
    @cached_property
    def publisher(self) -> bus.Publisher:
        return bus.Publisher()

    @cached_property
    def db(self):
        return db.connect()

    def decide(self, trace_id: str, decision: dict) -> None:
        """Record every agent decision (statistics requirement: decisions per agent)."""
        self.db.execute("INSERT INTO agent_decisions (agent, trace_id, decision) VALUES (%s, %s, %s)",
                        (self.name, trace_id, json.dumps(decision, default=str)))
        self.t["processed"].add(1, {"agent": self.name})

    def run(self, topics: list[str], handler) -> None:
        self.log.info("%s consuming %s", self.name, topics)
        bus.consume(self.name, topics, handler)
