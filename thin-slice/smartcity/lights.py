"""Client for the team's traffic-light control API (APIs/trafficControlAPI.py, run as an HTTP server)."""
import httpx

from smartcity import config


def nearest(lat: float, lon: float, radius_m: float = 400, limit: int = 3) -> list[dict]:
    r = httpx.get(f"{config.TRAFFIC_LIGHTS_URL}/lights",
                  params={"lat": lat, "lon": lon, "radius": radius_m, "limit": limit}, timeout=5)
    r.raise_for_status()
    return r.json()["lights"]


def hold(site_ids: list[str], state: str, seconds: int) -> list[dict]:
    """Override lights for `seconds`, after which they return to their automatic cycle."""
    body = [{"site_id": s, "state": state, "duration": seconds} for s in site_ids]
    r = httpx.post(f"{config.TRAFFIC_LIGHTS_URL}/lights/status", json=body, timeout=5)
    r.raise_for_status()
    return r.json()


def status(site_ids: list[str]) -> list[dict]:
    r = httpx.get(f"{config.TRAFFIC_LIGHTS_URL}/lights/status", params={"ids": ",".join(site_ids)}, timeout=5)
    r.raise_for_status()
    return r.json()
