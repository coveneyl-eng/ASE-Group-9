"""Message formats for every Kafka topic, defined once (DRY).

TypeScript mirrors live in portal/src/messages.ts.
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)  # follows one reading end-to-end
    created_at: datetime = Field(default_factory=now)


# flood.readings
class SensorReading(Message):
    sensor_id: str
    kind: Literal["water_level_m", "drain_level_pct", "tide_m", "rain_forecast_mm"]
    value: float
    lon: float
    lat: float
    source: str  # mqtt | opw | erddap | met_eireann
    observed_at: datetime = Field(default_factory=now)


# flood.events
class FloodEvent(Message):
    sensor_id: str
    level_m: float
    threshold_m: float
    lon: float
    lat: float
    observed_at: datetime


# flood.forecast
class FloodForecast(Message):
    horizon_hours: int
    predicted_level_m: float
    expected_impact: Literal["none", "minor", "major"]


# flood.impacts
class AssetImpact(BaseModel):
    asset_id: int
    name: str
    kind: str
    status: Literal["safe", "caution", "unsafe"]


class FloodImpact(Message):
    event_id: str
    sensor_id: str
    extent_geojson: dict
    impacts: list[AssetImpact]
    observed_at: datetime


# event.upcoming
class UpcomingEvent(Message):
    event_name: str
    venue: str
    lon: float
    lat: float
    starts_at: datetime
    expected_attendance: int


# event.plans
class EventPlan(Message):
    event_id: str
    event_name: str
    expected_attendance: int
    lon: float
    lat: float
    venue_access: Literal["open", "restricted"]
    predicted_extra_cars: int
    crowd_plan: str


# event.transport
class TransportPlan(Message):
    event_id: str
    extra_buses: int
    routes: list[str]


# traffic.flow
class TrafficFlow(Message):
    junction_id: str
    speed_ratio: float  # TomTom current / free-flow speed: 1.0 free, 0.3 heavy congestion
    level: str  # free | moderate | heavy | standstill | unknown (trafficCongestionAPI.congestionLevel)
    lon: float
    lat: float


# traffic.signals
class SignalCommand(Message):
    junction_id: str
    site_ids: list[str]  # SCATS sites in static/TrafficLightLocations (trafficControlAPI)
    state: Literal["green", "red"]
    seconds: int


# traffic.reroute
class RerouteCommand(Message):
    impact_id: str
    from_node: int
    to_node: int
    path_edges: list[int]
    avoided_edges: list[int]
    total_cost: float
    closed_light_sites: list[str] = []  # lights held red to stop traffic entering the flood


# dispatch.approved (Approval Service, role-checked official sign-off)
class DispatchApproval(Message):
    impact_id: str
    action: Literal["dispatch_responders", "close_roads", "reject"]
    approved_by: str
    role: str
    report_blob: str


# notifications.sent (written by the Notification Agent for the portal/audit)
class NotificationSent(Message):
    channel: Literal["sms", "email", "websocket"]
    recipient: str
    text: str
    latency_ms: float
    delivered: bool
    dry_run: bool


TOPICS = {
    "flood.readings": SensorReading,
    "flood.events": FloodEvent,
    "flood.forecast": FloodForecast,
    "flood.impacts": FloodImpact,
    "event.upcoming": UpcomingEvent,
    "event.watch": UpcomingEvent,
    "event.plans": EventPlan,
    "event.transport": TransportPlan,
    "traffic.flow": TrafficFlow,
    "traffic.congestion": TrafficFlow,
    "traffic.signals": SignalCommand,
    "traffic.reroute": RerouteCommand,
    "dispatch.approved": DispatchApproval,
    "notifications.sent": NotificationSent,
}
