import os
from datetime import datetime, timedelta, timezone
import requests

BASE = "https://app.ticketmaster.com/discovery/v2"
API_KEY = os.environ["TICKETMASTER_API_KEY"]

def _get(path, params=None):
    params = {**(params or {}), "apikey": API_KEY}
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Ticketmaster error on {path}: {e}")
        return None

def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") 

def upcomingDublinEvents(days_ahead=7, size=100):
    """Upcoming events in Dublin, flattened into what the agents actually need."""
    now = datetime.now(timezone.utc)
    data = _get("/events.json", {
        "countryCode": "IE",
        "city": "Dublin",
        "startDateTime": _iso(now),
        "endDateTime": _iso(now + timedelta(days=days_ahead)),
        "sort": "date,asc",
        "size": size,
    })
    if not data or "_embedded" not in data:      # no events -> no _embedded key
        return []
    events = []
    for e in data["_embedded"]["events"]:
        venue = (e.get("_embedded", {}).get("venues") or [{}])[0]
        loc = venue.get("location", {})
        cls = (e.get("classifications") or [{}])[0]
        events.append({
            "event_id": e["id"],
            "name": e["name"],
            "start": e["dates"]["start"].get("dateTime"),   # UTC, may be missing if TBA
            "local_date": e["dates"]["start"].get("localDate"),
            "local_time": e["dates"]["start"].get("localTime"),
            "status": e["dates"].get("status", {}).get("code"),  # onsale / cancelled / ...
            "category": cls.get("segment", {}).get("name"),      # Music, Sports, ...
            "venue_id": venue.get("id"),
            "venue": venue.get("name"),
            "lat": float(loc["latitude"]) if "latitude" in loc else None,
            "lon": float(loc["longitude"]) if "longitude" in loc else None,
        })
    return events

def dublinVenues(keyword=None):
    params = {"countryCode": "IE", "city": "Dublin", "size": 50}
    if keyword:
        params["keyword"] = keyword
    data = _get("/venues.json", params)
    return data["_embedded"]["venues"] if data and "_embedded" in data else []

if __name__ == "__main__":
    for ev in upcomingDublinEvents():
        print(f"{ev['local_date']} {ev['local_time'] or '--:--'}  {ev['venue']:<25} {ev['name']}")
