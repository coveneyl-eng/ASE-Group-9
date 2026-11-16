## Marine Institute Irish National Tide Gauge Network (ERDDAP). No API key needed.

import requests

API_URL = "https://erddap.marine.ie/erddap/tabledap/IrishNationalTideGaugeNetwork.json"
HEADERS = {"User-Agent": "FloodDetector/1.0"}
FIELDS = "time,station_id,latitude,longitude,Water_Level_OD_Malin,QC_Flag"


def tideGaugeReadings(stations='Dublin Port|Howth.*', hours=2):
    ## returns {"columnNames": [...], "rows": [[...], ...]} for the matching stations over the last `hours`
    query = f'{FIELDS}&station_id=~"{stations}"&time>=now-{hours}hours'
    try:
        r = requests.get(f"{API_URL}?{query}", headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.json()["table"]
    except requests.exceptions.RequestException as e:
        print(f"Marine Institute error: {e}")
        return None


if __name__ == "__main__":
    table = tideGaugeReadings()
    for row in (table or {}).get("rows", [])[:5]:
        print(row)
