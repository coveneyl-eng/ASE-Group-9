"""Unit tests that run without the stack (CI stage 1). The live end-to-end check is smartcity/verify.py."""
import os
from datetime import datetime, timezone

import jwt
import pytest

os.environ.setdefault("OFFLINE", "1")

from smartcity.models import FloodImpact, SensorReading, TOPICS  # noqa: E402


def test_every_topic_has_a_model():
    assert {"flood.readings", "flood.impacts", "traffic.reroute", "dispatch.approved"} <= TOPICS.keys()


def test_reading_rejects_unknown_kind():
    with pytest.raises(ValueError):
        SensorReading(sensor_id="x", kind="banana", value=1, lon=0, lat=0, source="t")


def test_impact_roundtrip_json():
    impact = FloodImpact(event_id="e", sensor_id="s", extent_geojson={"type": "Point", "coordinates": [0, 0]},
                         impacts=[{"asset_id": 1, "name": "A", "kind": "health", "status": "unsafe"}],
                         observed_at=datetime.now(timezone.utc))
    assert FloodImpact.model_validate_json(impact.model_dump_json()) == impact


def test_ingest_parsers_read_fixtures():
    from smartcity.services import ingest
    opw = ingest.opw_readings()
    assert opw and all(r.kind == "water_level_m" and ingest.in_dublin(r.lon, r.lat) for r in opw)
    assert "Sandy Mills" not in {r.sensor_id for r in opw}  # outside Dublin filtered out
    assert ingest.marine_tide()[0].value == pytest.approx(1.91)  # latest Dublin Port row
    assert ingest.met_eireann_rain()[0].value == pytest.approx(16.1)
    ev = ingest.ticketmaster_events()[0]
    assert ev.venue == "Aviva Stadium" and ev.expected_attendance == 51700
    flows = {f.junction_id: f for f in ingest.tomtom_flows()}
    assert flows["Aviva Stadium"].level == "heavy" and "3Arena" not in flows  # null TomTom reading skipped
    assert ingest.nta_trip_updates() == 2


def test_team_api_modules_are_importable():
    from smartcity import team_apis
    for name in ("opwAPI", "marineTideAPI", "metEireannAPI", "busAPI", "SMSapi"):
        assert team_apis.load(name) is not None, name
    os.environ.pop("TICKETMASTER_API_KEY", None)
    assert team_apis.load("ticketmasterAPI") is None  # missing key -> fixture, not a crash


def test_predictor_grades_and_model():
    from smartcity.agents import flood_predictor as fp
    assert fp.grade(2.7) == "major" and fp.grade(1.9) == "minor" and fp.grade(1.0) == "none"
    heavy = fp.model.predict([[50.0, 4.5, 1.2]])[0]
    light = fp.model.predict([[1.0, 2.0, 1.2]])[0]
    assert heavy > light


def test_signal_timing_is_bounded():
    from smartcity.agents.traffic_control import green_time
    assert green_time(1.0) == 20 and green_time(0.0) == 90 and green_time(0.3) == 76


def test_jwt_roles():
    os.environ["KEY_VAULT_URL"] = ""
    from smartcity.services import approval
    token = approval.issue_token("planner", "transport_planner")
    claims = jwt.decode(token, approval.JWT_SECRET, algorithms=["HS256"], issuer=approval.config.JWT_ISSUER)
    assert claims["role"] not in approval.CAN_APPROVE["dispatch_responders"]
    assert claims["role"] in approval.CAN_APPROVE["close_roads"]
