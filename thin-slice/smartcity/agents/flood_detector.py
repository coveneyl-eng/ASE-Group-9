"""Flood Detector: compares readings to CFRAM node thresholds, stores the time series, emits flood.events."""
from smartcity import config
from smartcity.agents.base import Agent
from smartcity.models import FloodEvent, SensorReading

agent = Agent("flood-detector")
DRAIN_ALERT_PCT = 85.0


def threshold_for(sensor_id: str) -> float:
    row = agent.db.execute("SELECT min(trigger_level_m) AS t FROM cfram_extents WHERE gauge_id = %s",
                           (sensor_id,)).fetchone()
    return row["t"] if row and row["t"] is not None else config.FLOOD_THRESHOLD_M


def handle(topic: str, r: SensorReading) -> None:
    agent.db.execute(
        "INSERT INTO sensor_readings (time, sensor_id, kind, value, source, geom) "
        "VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
        (r.observed_at, r.sensor_id, r.kind, r.value, r.source, r.lon, r.lat))
    if r.kind == "water_level_m":
        threshold = threshold_for(r.sensor_id)
        flooded = r.value >= threshold
    elif r.kind == "drain_level_pct":
        threshold, flooded = DRAIN_ALERT_PCT, r.value >= DRAIN_ALERT_PCT
    else:
        return  # tide / rain readings feed the predictor, not the detector
    if not flooded:
        return
    event = FloodEvent(trace_id=r.trace_id, sensor_id=r.sensor_id, level_m=r.value, threshold_m=threshold,
                       lon=r.lon, lat=r.lat, observed_at=r.observed_at)
    agent.publisher.publish("flood.events", event)
    agent.decide(r.trace_id, {"flood": True, "sensor": r.sensor_id, "level": r.value, "threshold": threshold})
    agent.log.info("FLOOD at %s: %.2f m >= %.2f m (trace %s)", r.sensor_id, r.value, threshold, r.trace_id)


if __name__ == "__main__":
    agent.run(["flood.readings"], handle)
