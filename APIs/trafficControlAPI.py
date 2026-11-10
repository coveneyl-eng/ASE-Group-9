"""
Traffic Control Agent - Stop Light API (demo)
=============================================

1. <Light Location: List>  getAllValues()
   Locations of Dublin City Council traffic signals (SCATS sites), loaded from
   static/TrafficLightLocations (CSV)
   (https://data.smartdublin.ie/dataset/traffic-signals-and-scats-sites-locations-dcc)

2. <Light Status: List>  setLightStatus([(location, status), ...])
   Lets us control stop lights to ease traffic.

   There is no public API for controlling Dublin's real lights, so this part is
   SIMULATED. Every light runs a normal automatic cycle (green -> amber -> red),
   and the agent can override a light for a number of seconds, after which
   the light goes back to its automatic cycle.

Run
---
    python trafficControlAPI.py                  # HTTP server on :8001
    python trafficControlAPI.py --cli            # quick terminal demo

Endpoints
---------
    GET  /lights                         all light locations (getAllValues)
         ?q=amiens                       search by street name
         ?lat=53.35&lon=-6.26&radius=500 lights within 500 m, nearest first
         ?limit=20
    GET  /lights/status?ids=1,2,3        current status of some lights
    GET  /lights/<site_id>               location + status of one light
    POST /lights/status                  change lights (JSON list, see below)
    POST /lights/<site_id>/auto          hand a light back to its automatic cycle
    GET  /health

POST /lights/status body:
    [
      {"site_id": "2", "state": "green", "duration": 60},
      {"site_id": "3", "state": "red",   "duration": 60}
    ]
    state: "green" | "amber" | "red" | "auto"; duration in seconds (default 60, max 900)

Only the Python standard library is used, so nothing needs to be installed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "static" / "TrafficLightLocations"

STATES = ("green", "amber", "red")
# Normal automatic cycle, in seconds
GREEN_TIME, AMBER_TIME, RED_TIME = 30, 3, 30
CYCLE = GREEN_TIME + AMBER_TIME + RED_TIME
DEFAULT_OVERRIDE, MAX_OVERRIDE = 60, 900


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class LightLocation:
    site_id: str
    location: str
    lat: float
    lon: float


@dataclass
class LightStatus:
    site_id: str
    location: str
    state: str                    # green | amber | red
    mode: str                     # auto | manual
    seconds_left: int             # until the light changes (auto) or the override ends (manual)


# --------------------------------------------------------------------------- #
# Light locations
# --------------------------------------------------------------------------- #
def load_locations(path: Path = CSV_PATH) -> list[LightLocation]:
    lights, seen = [], {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            site_id = row["Site_ID"].strip()
            # The dataset has a few duplicate IDs for different junctions -> make them unique
            seen[site_id] = seen.get(site_id, 0) + 1
            if seen[site_id] > 1:
                site_id = f"{site_id}-{seen[site_id]}"
            lights.append(LightLocation(site_id, row["Location"].strip(),
                                        float(row["Lat"]), float(row["Long"])))
    return lights


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- #
# Stop Light API
# --------------------------------------------------------------------------- #
class StopLightAPI:
    def __init__(self, csv_path: Path = CSV_PATH):
        self.lights = load_locations(csv_path)
        self.by_id = {l.site_id: l for l in self.lights}
        self._overrides: dict[str, tuple[str, float]] = {}   # site_id -> (state, expires_at)
        self._lock = threading.Lock()

    # ---- <Light Location: List> ------------------------------------------- #
    def getAllValues(self, q: str | None = None, lat: float | None = None,
                     lon: float | None = None, radius_m: float | None = None,
                     limit: int | None = None) -> list[dict]:
        results = self.lights
        if q:
            q = q.lower()
            results = [l for l in results if q in l.location.lower()]
        out = [asdict(l) for l in results]
        if lat is not None and lon is not None:
            for item in out:
                item["distance_m"] = round(distance_m(lat, lon, item["lat"], item["lon"]))
            if radius_m is not None:
                out = [i for i in out if i["distance_m"] <= radius_m]
            out.sort(key=lambda i: i["distance_m"])
        return out[:limit] if limit else out

    # ---- <Light Status: List> --------------------------------------------- #
    def getLightStatus(self, site_id: str, now: float | None = None) -> LightStatus:
        light = self._get(site_id)
        now = time.time() if now is None else now
        with self._lock:
            override = self._overrides.get(site_id)
            if override and override[1] <= now:
                del self._overrides[site_id]
                override = None
        if override:
            state, expires = override
            return LightStatus(site_id, light.location, state, "manual", math.ceil(expires - now))
        state, left = self._auto_state(site_id, now)
        return LightStatus(site_id, light.location, state, "auto", left)

    def getLightStatuses(self, site_ids: list[str]) -> list[LightStatus]:
        return [self.getLightStatus(s) for s in site_ids]

    def setLightStatus(self, changes: list[dict]) -> list[LightStatus]:
        """
        changes: [{"site_id": "2", "state": "green", "duration": 60}, ...]
        Validates everything first, so either all changes apply or none do.
        """
        if not isinstance(changes, list) or not changes:
            raise ValueError("body must be a non-empty JSON list of changes")
        parsed = []
        for c in changes:
            if not isinstance(c, dict):
                raise ValueError("each change must be an object")
            site_id = str(c.get("site_id", "")).strip()
            self._get(site_id)
            state = str(c.get("state", "")).lower()
            if state not in STATES + ("auto",):
                raise ValueError(f"site {site_id}: state must be green, amber, red or auto")
            try:
                duration = float(c.get("duration", DEFAULT_OVERRIDE))
            except (TypeError, ValueError):
                raise ValueError(f"site {site_id}: duration must be a number of seconds")
            if not 0 < duration <= MAX_OVERRIDE:
                raise ValueError(f"site {site_id}: duration must be between 1 and {MAX_OVERRIDE} seconds")
            parsed.append((site_id, state, duration))

        now = time.time()
        with self._lock:
            for site_id, state, duration in parsed:
                if state == "auto":
                    self._overrides.pop(site_id, None)
                else:
                    self._overrides[site_id] = (state, now + duration)
        return [self.getLightStatus(s, now) for s, _, _ in parsed]

    def setAuto(self, site_id: str) -> LightStatus:
        return self.setLightStatus([{"site_id": site_id, "state": "auto"}])[0]

    # ---- helpers ---------------------------------------------------------- #
    def _get(self, site_id: str) -> LightLocation:
        try:
            return self.by_id[site_id]
        except KeyError:
            raise LookupError(f"no traffic light with site_id {site_id!r}") from None

    @staticmethod
    def _auto_state(site_id: str, now: float) -> tuple[str, int]:
        # Offset each site so the lights aren't all in sync
        offset = sum(ord(ch) for ch in site_id) * 7 % CYCLE
        t = (now + offset) % CYCLE
        if t < GREEN_TIME:
            return "green", math.ceil(GREEN_TIME - t)
        if t < GREEN_TIME + AMBER_TIME:
            return "amber", math.ceil(GREEN_TIME + AMBER_TIME - t)
        return "red", math.ceil(CYCLE - t)


# --------------------------------------------------------------------------- #
# HTTP API (stdlib)
# --------------------------------------------------------------------------- #
API = None  # created in main()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body):
        payload = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):  # CORS preflight for browser frontends
        self._send(204, {})

    def _route(self, method: str):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        try:
            if method == "GET" and parts == ["health"]:
                return self._send(200, {"status": "ok", "lights": len(API.lights)})

            if method == "GET" and parts == ["lights"]:
                lat, lon = q.get("lat"), q.get("lon")
                lights = API.getAllValues(
                    q=q.get("q"),
                    lat=float(lat) if lat else None,
                    lon=float(lon) if lon else None,
                    radius_m=float(q["radius"]) if "radius" in q else None,
                    limit=int(q["limit"]) if "limit" in q else None,
                )
                return self._send(200, {"count": len(lights), "lights": lights})

            if method == "GET" and parts == ["lights", "status"]:
                ids = [i.strip() for i in q.get("ids", "").split(",") if i.strip()]
                if not ids:
                    raise ValueError("pass ?ids=1,2,3")
                return self._send(200, [asdict(s) for s in API.getLightStatuses(ids)])

            if method == "POST" and parts == ["lights", "status"]:
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length) or b"null")
                except json.JSONDecodeError:
                    raise ValueError("body must be valid JSON")
                return self._send(200, [asdict(s) for s in API.setLightStatus(body)])

            if method == "GET" and len(parts) == 2 and parts[0] == "lights":
                light = API._get(parts[1])
                return self._send(200, {**asdict(light), "status": asdict(API.getLightStatus(parts[1]))})

            if method == "POST" and len(parts) == 3 and parts[0] == "lights" and parts[2] == "auto":
                return self._send(200, asdict(API.setAuto(parts[1])))

            return self._send(404, {"error": "unknown endpoint, see the docstring in trafficControlAPI.py"})
        except LookupError as e:
            return self._send(404, {"error": e.args[0]})
        except ValueError as e:
            return self._send(400, {"error": str(e)})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


def main():
    global API
    p = argparse.ArgumentParser(description="Traffic Control Agent - Stop Light API demo")
    p.add_argument("--cli", action="store_true", help="run a short terminal demo instead of the server")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()
    API = StopLightAPI()

    if args.cli:
        print(f"Loaded {len(API.lights)} traffic lights from {CSV_PATH.name}\n")
        print("5 nearest lights to O'Connell Bridge:")
        for l in API.getAllValues(lat=53.3473, lon=-6.2591, limit=5):
            print(f"  [{l['site_id']:>5}] {l['location']:<45} {l['distance_m']:>4} m")
        ids = [l["site_id"] for l in API.getAllValues(q="amiens st")][:3]
        print("\nStatus before:")
        for s in API.getLightStatuses(ids):
            print(f"  [{s.site_id:>5}] {s.location:<35} {s.state:<5} ({s.mode}, {s.seconds_left}s)")
        print("\nAgent: hold Amiens St green for 2 minutes to clear a queue")
        for s in API.setLightStatus([{"site_id": i, "state": "green", "duration": 120} for i in ids]):
            print(f"  [{s.site_id:>5}] {s.location:<35} {s.state:<5} ({s.mode}, {s.seconds_left}s)")
        return

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Stop Light API: {len(API.lights)} lights on http://localhost:{args.port}/lights  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
