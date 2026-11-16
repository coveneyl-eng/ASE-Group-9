## Geological Survey Ireland: NYU 2015 Dublin city LiDAR tiles (1 m surface model). No API key needed.

import requests

API_URL = ("https://gsi.geodata.gov.ie/server/rest/services/Lidar/"
           "IE_GSI_LiDAR_Coverage_NYU_Dublin_IE26_ITM/FeatureServer/4/query")
HEADERS = {"User-Agent": "FloodDetector/1.0"}


def lidarTiles():
    ## returns a list of {"DATA_NAME": ..., "DATA_URL": ...} for every LiDAR tile over Dublin city
    params = {"where": "1=1", "outFields": "DATA_URL,DATA_NAME", "returnGeometry": "false", "f": "json"}
    try:
        r = requests.get(API_URL, headers=HEADERS, params=params, timeout=60)
        r.raise_for_status()
        return [f["attributes"] for f in r.json()["features"]]
    except requests.exceptions.RequestException as e:
        print(f"GSI LiDAR error: {e}")
        return None


def downloadTile(url, path):
    ## downloads one zipped GeoTIFF tile to `path`; returns the path, or None if it failed
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return path
    except requests.exceptions.RequestException as e:
        print(f"GSI LiDAR error on {url}: {e}")
        return None


if __name__ == "__main__":
    for t in lidarTiles() or []:
        print(t["DATA_NAME"], t["DATA_URL"])
