"""API tests against a PostGIS database loaded with tests/seed.sql.

Skipped when no database is reachable at DB_URL. Kafka is optional: the simulate
round-trip test only runs when KAFKA_TESTS=1.
"""
import json
import os
import time

import pytest
from sqlalchemy import create_engine, text

DB_URL = os.getenv("DB_URL", "postgresql+psycopg://flood:flood@localhost:5432/flood")

try:
    with create_engine(DB_URL, connect_args={"connect_timeout": 2}).connect() as c:
        c.execute(text("SELECT 1 FROM cfram_nodes LIMIT 1"))
    DB_OK = True
except Exception:
    DB_OK = False

pytestmark = pytest.mark.skipif(not DB_OK, reason="seeded database not reachable at DB_URL")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.app import app
    with TestClient(app) as c:
        yield c


def test_health_lists_layers(client):
    h = client.get("/api/health").json()
    names = {c["name"] for c in h["components"]}
    assert {"PostgreSQL", "Extensions", "Kafka"} <= names
    layers = {l["table"]: l for l in h["layers"]}
    assert layers["cfram_nodes"]["rows"] > 0
    assert layers["icwws_points"]["rows"] is None  # deliberately missing from the seed


def test_readings_excludes_simulated(client):
    r = client.get("/api/readings").json()
    assert r["dublin_port"], "expected a Dublin Port series"
    assert all(x["source"] != "simulated" for x in r["latest"])


@pytest.mark.parametrize("level, band, unsafe", [(2.0, None, 0), (2.9, "0.5%", 4), (3.1, "0.1%", 7)])
def test_flood_what_if(client, level, band, unsafe):
    f = client.get("/api/flood", params={"level": level}).json()
    assert f["band"] == band
    assert f["assets"]["by_grade"].get("unsafe", 0) == unsafe
    if band:
        assert f["extent"]["type"] in ("Polygon", "MultiPolygon")


def test_flood_items_sorted_worst_first(client):
    items = client.get("/api/flood", params={"level": 2.9}).json()["assets"]["items"]
    order = {"unsafe": 0, "caution": 1, "safe": 2}
    assert [order[i["grade"]] for i in items] == sorted(order[i["grade"]] for i in items)


@pytest.mark.skipif(os.getenv("KAFKA_TESTS") != "1", reason="set KAFKA_TESTS=1 with a broker running")
def test_simulate_reaches_live_feed(client):
    with client.websocket_connect("/api/live") as ws:
        time.sleep(2)
        assert client.post("/api/simulate", json={"level_m": 2.91}).status_code == 200
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = json.loads(ws.receive_text())
            if msg["reading"].get("level_m") == 2.91:
                assert msg["reading"]["source"] == "simulated"
                return
        pytest.fail("simulated reading never arrived on /api/live")
