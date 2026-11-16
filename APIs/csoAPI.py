## Central Statistics Office (CSO): Census 2022 small area boundaries and population. No API key needed.

import time
import requests

CKAN_URL = "https://data.gov.ie/api/3/action/package_show"
SMALL_AREAS_ID = "cso-small-areas-national-statistical-boundaries-2022-generalised-20m"
SAPS_URL = "https://www.cso.ie/en/media/csoie/census/census2022/SAPS_2022_Small_Area_UR_171024.csv"
HEADERS = {"User-Agent": "FloodDetector/1.0"}
BUSY = (202, 429, 502, 503, 504)     # 202 = ArcGIS Hub is still generating the file


def _get(url, params=None, tries=8):
    try:
        for attempt in range(tries):
            r = requests.get(url, headers=HEADERS, params=params, timeout=180)
            if r.status_code not in BUSY:
                break
            time.sleep(min(5 * 2 ** attempt, 120))
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        print(f"CSO error on {url}: {e}")
        return None


def smallAreaBoundaries():
    ## returns GeoJSON bytes of every Census 2022 small area in Ireland
    meta = _get(CKAN_URL, {"id": SMALL_AREAS_ID})
    if meta is None:
        return None
    resources = meta.json()["result"]["resources"]
    url = next(r["url"] for r in resources if r["format"].lower() in ("geojson", "json"))
    r = _get(url)
    return r.content if r is not None else None


def smallAreaPopulation():
    ## returns the Census 2022 Small Area Population Statistics (SAPS) as CSV bytes
    r = _get(SAPS_URL)
    return r.content if r is not None else None


if __name__ == "__main__":
    print(f"{len(smallAreaPopulation() or b'')} bytes of SAPS CSV")
