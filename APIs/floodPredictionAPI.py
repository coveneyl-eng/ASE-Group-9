"""
Flood Prediction Agent - demo API
=================================

Input : weather forecast from a Weather API  -> getAllValues()
Output: list of dates with weather likely to cause a flood ("Dates of Concern")

Weather sources
---------------
- met        Met Eireann open forecast API (no key needed, default)
             https://weather.apis.ie/docs/#met-eireann-weatherforecast-api
- meteosource Meteosource free tier (needs env var METEOSOURCE_API_KEY)
             https://www.meteosource.com/weather-api-dublin
- mock       Built-in stormy week, so the demo always shows some flood dates

Run
---
    python floodPredictionAPI.py                       # HTTP server on :8000
    python floodPredictionAPI.py --cli                 # print result to terminal
    python floodPredictionAPI.py --cli --source mock   # offline demo

Endpoints
---------
    GET /flood-dates?lat=53.35&lon=-6.26&source=met   -> Dates of Concern
    GET /weather?lat=53.35&lon=-6.26&source=met       -> getAllValues() (daily summary)
    GET /health

Only the Python standard library is used, so nothing needs to be installed.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DUBLIN = (53.35, -6.26)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class DailyWeather:
    date: str                       # ISO date, e.g. "2026-11-10"
    rain_mm: float = 0.0            # total precipitation for the day
    max_rain_mm_per_hour: float = 0.0
    max_rain_probability: float = 0.0   # percent, 0 if source doesn't give it
    max_wind_gust_mps: float = 0.0
    min_pressure_hpa: float | None = None


@dataclass
class DateOfConcern:
    date: str
    risk: str                       # "moderate" | "high" | "severe"
    score: int
    rain_mm: float
    rain_3day_mm: float
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Weather sources  (each implements getAllValues)
# --------------------------------------------------------------------------- #
def _http_get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ASE-Group-9-FloodDemo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class MetEireannSource:
    """Met Eireann point forecast (XML). Hourly for ~2 days, then 3h/6h steps out to ~10 days."""

    URL = "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast?lat={lat};long={lon}"

    def getAllValues(self, lat: float, lon: float) -> list[DailyWeather]:
        root = ET.fromstring(_http_get(self.URL.format(lat=lat, lon=lon)))
        days: dict[str, DailyWeather] = {}

        def day(d: str) -> DailyWeather:
            return days.setdefault(d, DailyWeather(date=d))

        rain_intervals = []
        for t in root.iter("time"):
            start = datetime.fromisoformat(t.get("from").replace("Z", "+00:00"))
            end = datetime.fromisoformat(t.get("to").replace("Z", "+00:00"))
            loc = t.find("location")
            if loc is None:
                continue
            precip = loc.find("precipitation")
            if precip is not None and end > start:
                rain_intervals.append((start, end, precip))
                continue
            # instantaneous values (wind, pressure, ...)
            d = day(start.date().isoformat())
            gust = loc.find("windGust")
            if gust is not None:
                d.max_wind_gust_mps = max(d.max_wind_gust_mps, float(gust.get("mps", 0)))
            pr = loc.find("pressure")
            if pr is not None:
                p = float(pr.get("value"))
                d.min_pressure_hpa = p if d.min_pressure_hpa is None else min(d.min_pressure_hpa, p)

        # Sum rain over non-overlapping intervals (shortest interval wins if any overlap)
        rain_intervals.sort(key=lambda x: (x[0], x[1] - x[0]))
        last_end = None
        for start, end, precip in rain_intervals:
            if last_end is not None and start < last_end:
                continue
            last_end = end
            mm = float(precip.get("value", 0))
            hours = (end - start).total_seconds() / 3600
            d = day(start.date().isoformat())
            d.rain_mm += mm
            d.max_rain_mm_per_hour = max(d.max_rain_mm_per_hour, mm / hours)
            d.max_rain_probability = max(d.max_rain_probability, float(precip.get("probability", 0) or 0))

        return _finish(days)


class MeteosourceSource:
    """Meteosource free tier, daily section. Needs METEOSOURCE_API_KEY."""

    URL = "https://www.meteosource.com/api/v1/free/point"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("METEOSOURCE_API_KEY")
        if not self.api_key:
            raise ValueError("Set METEOSOURCE_API_KEY to use the meteosource source")

    def getAllValues(self, lat: float, lon: float) -> list[DailyWeather]:
        q = urllib.parse.urlencode(
            {"lat": lat, "lon": lon, "sections": "daily", "units": "metric",
             "language": "en", "key": self.api_key}
        )
        data = json.loads(_http_get(f"{self.URL}?{q}"))
        days = {}
        for item in data.get("daily", {}).get("data", []):
            all_day = item.get("all_day", {})
            rain = (all_day.get("precipitation") or {}).get("total") or 0.0
            wind = (all_day.get("wind") or {}).get("speed") or 0.0
            days[item["day"]] = DailyWeather(
                date=item["day"],
                rain_mm=float(rain),
                max_rain_mm_per_hour=float(rain) / 24,   # free tier has no hourly breakdown here
                max_wind_gust_mps=float(wind) * 1.5,     # rough gust estimate from mean wind
            )
        return _finish(days)


class MockSource:
    """Deterministic stormy week for demos / tests (no network)."""

    PATTERN = [  # rain_mm, peak mm/h, prob %, gust m/s, pressure
        (2.0, 0.5, 30, 10, 1012),
        (12.0, 2.0, 70, 14, 1003),
        (31.0, 6.5, 95, 24, 984),   # named storm
        (22.0, 4.0, 90, 19, 990),   # still raining on saturated ground
        (6.0, 1.0, 60, 12, 1001),
        (0.4, 0.2, 10, 8, 1018),
        (18.0, 3.5, 85, 16, 998),
    ]

    def getAllValues(self, lat: float, lon: float) -> list[DailyWeather]:
        today = date.today()
        return [
            DailyWeather((today + timedelta(days=i)).isoformat(), r, h, p, g, pr)
            for i, (r, h, p, g, pr) in enumerate(self.PATTERN)
        ]


def _finish(days: dict[str, DailyWeather]) -> list[DailyWeather]:
    out = sorted(days.values(), key=lambda d: d.date)
    for d in out:
        d.rain_mm = round(d.rain_mm, 1)
        d.max_rain_mm_per_hour = round(d.max_rain_mm_per_hour, 1)
    return out


SOURCES = {"met": MetEireannSource, "meteosource": MeteosourceSource, "mock": MockSource}


# --------------------------------------------------------------------------- #
# Flood Prediction Agent
# --------------------------------------------------------------------------- #
class FloodPredictionAgent:
    """
    Rule-based scoring. Thresholds are loosely based on Met Eireann rainfall
    warnings (yellow ~25mm/24h, orange ~40-50mm/24h) and are easy to tune.
    """

    DAILY_RAIN_MODERATE = 15.0    # mm / day
    DAILY_RAIN_HIGH = 25.0
    DAILY_RAIN_SEVERE = 40.0
    RAIN_3DAY = 50.0              # mm over 3 days -> saturated ground
    INTENSE_RAIN = 5.0            # mm / hour -> flash/surface-water flooding
    STORM_GUST = 20.0             # m/s (~72 km/h) -> coastal surge / blocked drains
    LOW_PRESSURE = 990.0          # hPa -> raised sea level (surge)

    def __init__(self, source):
        self.source = source

    def getAllValues(self, lat: float, lon: float) -> list[DailyWeather]:
        return self.source.getAllValues(lat, lon)

    def score_day(self, d: DailyWeather, rain_3day: float) -> tuple[int, list[str]]:
        score, reasons = 0, []
        if d.rain_mm >= self.DAILY_RAIN_SEVERE:
            score += 4; reasons.append(f"very heavy rain {d.rain_mm} mm")
        elif d.rain_mm >= self.DAILY_RAIN_HIGH:
            score += 3; reasons.append(f"heavy rain {d.rain_mm} mm")
        elif d.rain_mm >= self.DAILY_RAIN_MODERATE:
            score += 2; reasons.append(f"persistent rain {d.rain_mm} mm")

        if rain_3day >= self.RAIN_3DAY:
            score += 2; reasons.append(f"{rain_3day} mm over 3 days (saturated ground)")
        if d.max_rain_mm_per_hour >= self.INTENSE_RAIN:
            score += 2; reasons.append(f"intense bursts up to {d.max_rain_mm_per_hour} mm/h")
        if d.max_wind_gust_mps >= self.STORM_GUST:
            score += 1; reasons.append(f"storm gusts {d.max_wind_gust_mps:.0f} m/s")
        if d.min_pressure_hpa is not None and d.min_pressure_hpa <= self.LOW_PRESSURE:
            score += 1; reasons.append(f"deep low {d.min_pressure_hpa:.0f} hPa (surge risk)")
        if score and d.max_rain_probability and d.max_rain_probability < 50:
            score -= 1; reasons.append(f"low confidence ({d.max_rain_probability:.0f}% probability)")
        return score, reasons

    def get_dates_of_concern(self, lat: float = DUBLIN[0], lon: float = DUBLIN[1]) -> list[DateOfConcern]:
        days = self.getAllValues(lat, lon)
        rain_by_date = defaultdict(float, {d.date: d.rain_mm for d in days})
        concerns = []
        for d in days:
            dt = date.fromisoformat(d.date)
            rain_3day = round(sum(rain_by_date[(dt - timedelta(days=k)).isoformat()] for k in range(3)), 1)
            score, reasons = self.score_day(d, rain_3day)
            if score >= 2:
                risk = "severe" if score >= 6 else "high" if score >= 4 else "moderate"
                concerns.append(DateOfConcern(d.date, risk, score, d.rain_mm, rain_3day, reasons))
        return concerns


# --------------------------------------------------------------------------- #
# HTTP API (stdlib)
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict):
        payload = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/health":
            return self._send(200, {"status": "ok"})
        if url.path not in ("/flood-dates", "/weather"):
            return self._send(404, {"error": "try /flood-dates, /weather or /health"})
        try:
            lat, lon = float(q.get("lat", DUBLIN[0])), float(q.get("lon", DUBLIN[1]))
            source_name = q.get("source", "met")
            agent = FloodPredictionAgent(SOURCES[source_name]())
        except KeyError:
            return self._send(400, {"error": f"source must be one of {list(SOURCES)}"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        try:
            if url.path == "/weather":
                result = [asdict(d) for d in agent.getAllValues(lat, lon)]
                return self._send(200, {"source": source_name, "lat": lat, "lon": lon, "days": result})
            result = [asdict(d) for d in agent.get_dates_of_concern(lat, lon)]
            return self._send(200, {"source": source_name, "lat": lat, "lon": lon,
                                    "count": len(result), "dates_of_concern": result})
        except Exception as e:  # upstream API down, bad response, ...
            return self._send(502, {"error": f"weather source failed: {e}"})


def main():
    p = argparse.ArgumentParser(description="Flood Prediction Agent demo")
    p.add_argument("--cli", action="store_true", help="print result instead of starting server")
    p.add_argument("--source", default="met", choices=SOURCES)
    p.add_argument("--lat", type=float, default=DUBLIN[0])
    p.add_argument("--lon", type=float, default=DUBLIN[1])
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    if args.cli:
        agent = FloodPredictionAgent(SOURCES[args.source]())
        print(f"Daily forecast ({args.source}):")
        for d in agent.getAllValues(args.lat, args.lon):
            print(f"  {d.date}  rain {d.rain_mm:5.1f} mm  peak {d.max_rain_mm_per_hour:4.1f} mm/h"
                  f"  gust {d.max_wind_gust_mps:4.1f} m/s")
        concerns = agent.get_dates_of_concern(args.lat, args.lon)
        print(f"\nDates of concern: {len(concerns)}")
        for c in concerns:
            print(f"  {c.date}  {c.risk.upper():8} (score {c.score})  " + "; ".join(c.reasons))
        return

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Flood Prediction API on http://localhost:{args.port}/flood-dates  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
