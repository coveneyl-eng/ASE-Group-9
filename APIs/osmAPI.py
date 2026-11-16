## OpenStreetMap Overpass API: roads, buildings, bridges, rail and critical sites. No API key needed.

import time
import requests

API_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "FloodDetector/1.0"}
BUSY = (429, 502, 503, 504)          # the public server is busy: wait and try again


def infrastructureQuery(south, west, north, east):
    ## returns the raw OSM elements (with tags and geometry) for infrastructure inside the bounding box
    bbox = f"({south},{west},{north},{east})"
    query = f"""[out:json][timeout:300];
    ( way["highway"]{bbox}; way["building"]{bbox}; way["railway"~"rail|light_rail"]{bbox};
      nwr["amenity"~"hospital|clinic|school|fire_station|police"]{bbox}; nwr["power"="substation"]{bbox}; );
    out tags geom;"""
    try:
        for attempt in range(8):
            r = requests.post(API_URL, headers=HEADERS, data={"data": query}, timeout=360)
            if r.status_code not in BUSY:
                break
            time.sleep(min(5 * 2 ** attempt, 120))
        r.raise_for_status()
        return r.json()["elements"]
    except requests.exceptions.RequestException as e:
        print(f"Overpass error: {e}")
        return None


if __name__ == "__main__":
    elements = infrastructureQuery(53.34, -6.26, 53.35, -6.24)
    print(f"{len(elements or [])} OSM elements")
