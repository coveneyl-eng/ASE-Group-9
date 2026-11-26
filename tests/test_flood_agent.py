"""Unit tests for the Flood Detector agent. No Kafka or database is contacted: the agent builds its
database engine lazily and these tests only call its pure functions."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def agent():
    sys.path.insert(0, str(ROOT / "flood-thin-slice" / "agent"))
    try:
        return importlib.import_module("flood_agent")
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize("kind,depth,expected", [
    ("road", None, "unsafe"),        # unknown depth is treated as unsafe
    ("road", 0.05, "safe"),          # roads tolerate up to 0.10 m
    ("road", 0.20, "caution"),
    ("road", 0.30, "unsafe"),
    ("building", -0.5, "safe"),      # dry ground
    ("building", 0.10, "caution"),   # buildings tolerate nothing
    ("building", 0.15, "unsafe"),
])
def test_grade_thresholds(agent, kind, depth, expected):
    assert agent.grade(kind, depth) == expected


def test_grade_matches_dashboard_copy(agent):
    """The grading rules exist in three places; this fails if the agent and the dashboard drift apart."""
    sys.path.insert(0, str(ROOT / "dashboard"))
    try:
        flood = importlib.import_module("api.flood")
    finally:
        sys.path.pop(0)
    for kind in ("road", "building", "critical"):
        for depth in (None, -1.0, 0.0, 0.05, 0.10, 0.15, 0.29, 0.30, 2.0):
            assert agent.grade(kind, depth) == flood.grade(kind, depth), (kind, depth)


def test_kafka_config_plain_by_default(agent, monkeypatch):
    for name in ("KAFKA_SECURITY_PROTOCOL", "KAFKA_SASL_MECHANISM", "KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert agent.kafka_config() == {"bootstrap.servers": agent.KAFKA}


def test_kafka_config_adds_sasl_when_set(agent, monkeypatch):
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "user")
    conf = agent.kafka_config(**{"group.id": "g"})
    assert conf["security.protocol"] == "SASL_SSL"
    assert conf["sasl.username"] == "user"
    assert conf["group.id"] == "g"


def test_default_topics(agent):
    assert agent.IMPACT_TOPIC == "flood.impacts"
    assert agent.READINGS_TOPIC == "flood.readings"