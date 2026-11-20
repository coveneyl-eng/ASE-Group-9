"""Ingest workers: call the team's API clients (../APIs), validate, publish to Kafka.

Production cadence is the sources' own 5-15 minute cycle (KISS). With OFFLINE=1, or when a source or its
API key is unavailable, the matching fixture in fixtures/ is used so the slice still runs end to end.
    python -m smartcity.services.ingest --once
"""
import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from smartcity import bus, config, telemetry, team_apis
from smartcity.models import SensorReading, TrafficFlow, UpcomingEvent

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
DUBLIN_BBOX = (-6.45, 53.20, -6.05, 53.45)  # lon_min, lat_min, lon_max, lat_max
VENUE_CAPACITY = {"Aviva Stadium": 51700, "Croke Park": 82300, "3Arena": 13000}  # Ticketmaster gives no size

t = telemetry.setup("ingest-worker")


def call(module: str, fn: str, fixture: str, *args, parse=json.loads, **kwargs):
    """Call APIs/<module>.<fn>(); fall back to fixtures/<fixture>. Returns (data, 'live'|'fixture')."""
    if not config.OFFLINE:
        mod = team_apis.load(module)
        if mod is not None:
            try:
                data = getattr(mod, fn)(*args, **kwargs)
                if data is not None:
                    return data, "live"
            except Exception as exc:
                t["log"].warning("%s.%s failed (%s); using fixture", module, fn, exc)
    raw = (FIXTURES / fixture).read_text()
    return parse(raw) if parse else raw, "fixture"


def in_dublin(lon: float, lat: float) -> bool:
    return DUBLIN_BBOX[0] <= lon <= DUBLIN_BBOX[2] and DUBLIN_BBOX[1] <= lat <= DUBLIN_BBOX[3]


def opw_readings() -> list[SensorReading]:
    data, mode = call("opwAPI", "latestWaterLevels", "opw_latest.geojson")
    if isinstance(data, (bytes, str)):
        data = json.loads(data)
    out = []
    for f in data["features"]:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        if p.get("sensor_ref") != "0001" or not in_dublin(lon, lat) or p.get("value") in (None, ""):
            continue
        out.append(SensorReading(sensor_id=f"OPW-{p['station_ref']}", kind="water_level_m", value=float(p["value"]),
                                 lon=lon, lat=lat, source=f"opw:{mode}",
                                 observed_at=datetime.fromisoformat(p["datetime"].replace("Z", "+00:00"))))
    return out


def marine_tide() -> list[SensorReading]:
    table, mode = call("marineTideAPI", "tideGaugeReadings", "marine_tide_table.json", stations="Dublin Port")
    cols = table["columnNames"]
    rows = [dict(zip(cols, r)) for r in table["rows"] if r[cols.index("Water_Level_OD_Malin")] is not None]
    if not rows:
        return []
    latest = max(rows, key=lambda r: r["time"])
    return [SensorReading(sensor_id="MARINE-DUBLIN-PORT", kind="tide_m", value=float(latest["Water_Level_OD_Malin"]),
                          lon=float(latest["longitude"]), lat=float(latest["latitude"]), source=f"marine:{mode}",
                          observed_at=datetime.fromisoformat(latest["time"].replace("Z", "+00:00")))]


def met_eireann_rain() -> list[SensorReading]:
    xml, mode = call("metEireannAPI", "pointForecast", "met_eireann_forecast.xml", parse=None)
    root = ET.fromstring(xml)
    total, hours = 0.0, 0
    for node in root.iter("time"):  # sum precipitation over the next 6 hourly intervals
        p = node.find("location/precipitation")
        start, end = node.get("from"), node.get("to")
        if p is None or start == end:
            continue
        span = datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
        if span == timedelta(hours=1):
            total += float(p.get("value"))
            hours += 1
        if hours == 6:
            break
    return [SensorReading(sensor_id="MET-DUBLIN", kind="rain_forecast_mm", value=round(total, 1),
                          lon=-6.26, lat=53.35, source=f"met_eireann:{mode}")]


def ticketmaster_events() -> list[UpcomingEvent]:
    events, mode = call("ticketmasterAPI", "upcomingDublinEvents", "ticketmaster_events.json")
    out = []
    for e in events:
        if e.get("lat") is None or not e.get("start") or e.get("status") == "cancelled":
            continue
        out.append(UpcomingEvent(event_name=e["name"], venue=e.get("venue") or "?", lon=e["lon"], lat=e["lat"],
                                 expected_attendance=VENUE_CAPACITY.get(e.get("venue"), 5000),
                                 starts_at=datetime.fromisoformat(e["start"].replace("Z", "+00:00"))))
    t["log"].info("ticketmaster (%s): %d events", mode, len(out))
    return out


def tomtom_flows() -> list[TrafficFlow]:
    venues, mode = call("trafficCongestionAPI", "venueTraffic", "tomtom_venue_traffic.json")
    out = []
    for name, f in venues.items():
        if f and f.get("speed_ratio") is not None:
            out.append(TrafficFlow(junction_id=name, speed_ratio=f["speed_ratio"], level=f.get("level", "unknown"),
                                   lon=f["lon"], lat=f["lat"]))
    return out


def nta_trip_updates() -> int:
    data, mode = call("busAPI", "BusTripUpdatesQuery", "nta_gtfsr.json")
    if isinstance(data, str):
        data = json.loads(data)
    n = len(data.get("entity", []))
    t["log"].info("NTA GTFS-R (%s): %d trip updates", mode, n)
    return n


def run_once(publisher: bus.Publisher) -> dict:
    counts = {}
    for name, fn, topic in [("opw", opw_readings, "flood.readings"), ("marine", marine_tide, "flood.readings"),
                            ("met", met_eireann_rain, "flood.readings"),
                            ("ticketmaster", ticketmaster_events, "event.upcoming"),
                            ("tomtom", tomtom_flows, "traffic.flow")]:
        try:
            msgs = fn()
        except Exception:
            t["log"].exception("%s ingest failed; agents keep last known state", name)
            continue
        for m in msgs:
            publisher.publish(topic, m)
        counts[name] = len(msgs)
    counts["nta"] = nta_trip_updates()
    t["log"].info("ingest cycle published %s", counts)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=900)
    args = parser.parse_args()
    publisher = bus.Publisher()
    while True:
        run_once(publisher)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
