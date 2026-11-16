"""
TomTom Traffic API client - live congestion + incidents for Dublin

Docs: https://developer.tomtom.com/traffic-api/documentation
Auth: set the environment variable TOMTOM_API_KEY (never hardcode it).
      PowerShell:  $env:TOMTOM_API_KEY = "your-key"

    pip install requests

Free evaluation plan: 2,500 traffic requests per day, so cache results and
don't poll every second.

Endpoints used
--------------
GET /traffic/services/4/flowSegmentData/absolute/10/json?point=lat,lon
    -> current vs free-flow speed on the road nearest to a point
GET /traffic/services/5/incidentDetails?bbox=minLon,minLat,maxLon,maxLat
    -> accidents, jams, road works, closures, flooding... inside a box
"""

import os
import requests

BASE = "https://api.tomtom.com/traffic/services"
API_KEY = os.environ["TOMTOM_API_KEY"]
# API Key: wHhwTgGCdf90dX84F3N0cuFlQZb2J4rL

# Rough bounding box around Dublin city (minLon, minLat, maxLon, maxLat)
DUBLIN_BBOX = (-6.45, 53.25, -6.05, 53.45)

# A few event venues to watch (approximate coordinates)
VENUES = {
    "Aviva Stadium": (53.3352, -6.2285),
    "Croke Park": (53.3607, -6.2511),
    "3Arena": (53.3475, -6.2285),
}

# TomTom incident categories (properties.iconCategory)
INCIDENT_TYPES = {
    0: "Unknown", 1: "Accident", 2: "Fog", 3: "Dangerous conditions", 4: "Rain",
    5: "Ice", 6: "Jam", 7: "Lane closed", 8: "Road closed", 9: "Road works",
    10: "Wind", 11: "Flooding", 14: "Broken down vehicle",
}
DELAY_LEVELS = {0: "unknown", 1: "minor", 2: "moderate", 3: "major", 4: "undefined"}


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _get(path, params=None):
    params = {**(params or {}), "key": API_KEY}
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        # the key is in the URL, so hide it before printing
        print(f"TomTom error on {path}: {str(e).replace(API_KEY, '***')}")
        return None


# --------------------------------------------------------------------------- #
# Traffic flow
# --------------------------------------------------------------------------- #
def flowAt(lat, lon):
    """Live traffic on the road segment closest to (lat, lon)."""
    data = _get("/4/flowSegmentData/absolute/10/json",
                {"point": f"{lat},{lon}", "unit": "KMPH"})
    if not data or "flowSegmentData" not in data:
        return None
    f = data["flowSegmentData"]
    current, free = f.get("currentSpeed"), f.get("freeFlowSpeed")
    ratio = round(current / free, 2) if current is not None and free else None
    return {
        "lat": lat,
        "lon": lon,
        "current_speed_kmh": current,
        "free_flow_speed_kmh": free,
        "speed_ratio": ratio,                       # 1.0 = free flowing, 0.3 = heavy congestion
        "current_travel_time_s": f.get("currentTravelTime"),
        "free_flow_travel_time_s": f.get("freeFlowTravelTime"),
        "road_closed": f.get("roadClosure", False),
        "confidence": f.get("confidence"),          # 0-1, how reliable the reading is
    }


def congestionLevel(ratio):
    """Turn a speed ratio into a label the agents can reason about."""
    if ratio is None:
        return "unknown"
    if ratio >= 0.8:
        return "free"
    if ratio >= 0.5:
        return "moderate"
    if ratio >= 0.25:
        return "heavy"
    return "standstill"


def venueTraffic():
    """Congestion next to each venue in VENUES (1 request per venue)."""
    out = {}
    for name, (lat, lon) in VENUES.items():
        flow = flowAt(lat, lon)
        if flow:
            flow["level"] = congestionLevel(flow["speed_ratio"])
        out[name] = flow
    return out


def gridPoints(bbox=DUBLIN_BBOX, rows=5, cols=6):
    """Evenly spaced (lat, lon) points covering the bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return [
        (round(min_lat + (r + 0.5) * (max_lat - min_lat) / rows, 5),
         round(min_lon + (c + 0.5) * (max_lon - min_lon) / cols, 5))
        for r in range(rows) for c in range(cols)
    ]


def citywideTraffic(rows=5, cols=6):
    """
    Traffic across all of Dublin, sampled on a rows x cols grid
    (5 x 6 = 30 requests). TomTom snaps each point to the nearest road;
    points with no road nearby (e.g. in Dublin Bay) are skipped.
    """
    readings = []
    for lat, lon in gridPoints(rows=rows, cols=cols):
        f = flowAt(lat, lon)
        if f and f["speed_ratio"] is not None:
            f["level"] = congestionLevel(f["speed_ratio"])
            readings.append(f)
    if not readings:
        return {"points": [], "average_speed_ratio": None, "level": "unknown", "worst": []}
    avg = round(sum(r["speed_ratio"] for r in readings) / len(readings), 2)
    return {
        "points": readings,
        "average_speed_ratio": avg,                 # whole-city congestion in one number
        "level": congestionLevel(avg),
        "worst": sorted(readings, key=lambda r: r["speed_ratio"])[:5],
        "closed_roads": [r for r in readings if r["road_closed"]],
    }


# --------------------------------------------------------------------------- #
# Incidents
# --------------------------------------------------------------------------- #
def incidents(bbox=DUBLIN_BBOX):
    """Current incidents inside bbox = (minLon, minLat, maxLon, maxLat)."""
    fields = ("{incidents{type,geometry{type,coordinates},properties{id,iconCategory,"
              "magnitudeOfDelay,events{description},startTime,endTime,from,to,"
              "length,delay,roadNumbers}}}")
    data = _get("/5/incidentDetails", {
        "bbox": ",".join(str(x) for x in bbox),
        "fields": fields,
        "language": "en-GB",
        "timeValidityFilter": "present",
    })
    if not data:
        return []
    out = []
    for inc in data.get("incidents", []):
        p = inc.get("properties", {})
        coords = inc.get("geometry", {}).get("coordinates") or []
        # Point -> [lon, lat]; LineString -> [[lon, lat], ...]; take the first point
        first = coords[0] if coords and isinstance(coords[0], list) else coords
        out.append({
            "id": p.get("id"),
            "type": INCIDENT_TYPES.get(p.get("iconCategory"), "Other"),
            "description": "; ".join(e.get("description", "") for e in p.get("events", [])),
            "delay_level": DELAY_LEVELS.get(p.get("magnitudeOfDelay"), "unknown"),
            "delay_s": p.get("delay"),
            "from": p.get("from"),
            "to": p.get("to"),
            "roads": p.get("roadNumbers"),
            "start": p.get("startTime"),
            "end": p.get("endTime"),
            "lat": first[1] if len(first) == 2 else None,
            "lon": first[0] if len(first) == 2 else None,
        })
    return out


if __name__ == "__main__":
    city = citywideTraffic()
    print(f"Dublin overall: {city['level']} (avg speed ratio {city['average_speed_ratio']}, "
          f"{len(city['points'])} points)")
    print("Most congested points:")
    for f in city["worst"]:
        print(f"  ({f['lat']:.4f}, {f['lon']:.4f})  {f['current_speed_kmh']:>3}/"
              f"{f['free_flow_speed_kmh']:<3} km/h  -> {f['level']}")

    incs = incidents()
    print(f"\n{len(incs)} incidents in Dublin right now:")
    for i in incs[:15]:
        print(f"  {i['type']:<20} {i['delay_level']:<9} {i['from'] or ''} -> {i['to'] or ''}")