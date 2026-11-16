## Met Eireann open data: national weather warnings and a point forecast. No API key needed.

import requests

WARNINGS_URL = "https://www.met.ie/Open_Data/json/warning_IRELAND.json"
FORECAST_URL = "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast"
HEADERS = {"User-Agent": "FloodDetector/1.0"}


def weatherWarnings():
    ## returns a list of the currently active weather warnings for Ireland
    try:
        r = requests.get(WARNINGS_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Met Eireann error on warnings: {e}")
        return None


def pointForecast(lat=53.35, lon=-6.26):
    ## returns the raw XML point forecast (rain, wind, pressure) for about 10 days ahead
    try:
        r = requests.get(f"{FORECAST_URL}?lat={lat};long={lon}", headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        print(f"Met Eireann error on forecast: {e}")
        return None


if __name__ == "__main__":
    print(f"{len(weatherWarnings() or [])} active warnings")
