## Office of Public Works (OPW): live river levels from waterlevel.ie and the
## CFRAM / ICWWS flood map datasets on floodinfo.ie. No API key needed.

import time
import requests

WATER_LEVEL_URL = "http://waterlevel.ie/geojson/latest/"
OPW_S3 = "https://s3.eu-west-1.amazonaws.com/catalogue.floodinfo.opw"
CFRAM_NODES_URL = f"{OPW_S3}/cfram/esds_nodes_current.zip"
CFRAM_RIVER_URL = f"{OPW_S3}/cfram/esds_floodmap_ext_f_c.zip"
CFRAM_COAST_URL = f"{OPW_S3}/cfram/esds_floodmap_ext_c_c.zip"
ICWWS_URL = (f"{OPW_S3}/icwws-2018-phase1-national-coastal-extreme-water-level-estimation-points-itm-osgm15.csv")

HEADERS = {"User-Agent": "FloodDetector/1.0"}


def _download(url, path):
    """Stream a large file to disk. Returns the path, or None if the request failed."""
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return path
    except requests.exceptions.RequestException as e:
        print(f"OPW error on {url}: {e}")
        return None


def latestWaterLevels():
    ## returns the latest reading of every OPW hydrometric sensor in Ireland, as GeoJSON bytes
    try:
        r = requests.get(WATER_LEVEL_URL, headers=HEADERS, params={"t": int(time.time())}, timeout=60)
        r.raise_for_status()
        return r.content
    except requests.exceptions.RequestException as e:
        print(f"OPW error on {WATER_LEVEL_URL}: {e}")
        return None


def downloadCframNodes(path):
    ## CFRAM flood model nodes (water level for each AEP band), zipped shapefile
    return _download(CFRAM_NODES_URL, path)


def downloadCframRiverExtents(path):
    ## CFRAM fluvial (river) flood extents for the 10%, 1% and 0.1% AEP bands, zipped shapefiles
    return _download(CFRAM_RIVER_URL, path)


def downloadCframCoastalExtents(path):
    ## CFRAM coastal flood extents for the 10%, 0.5% and 0.1% AEP bands, zipped shapefiles
    return _download(CFRAM_COAST_URL, path)


def downloadCoastalExtremeLevels(path):
    ## ICWWS 2018 coastal extreme water level estimation points (ITM, OD Malin), CSV
    return _download(ICWWS_URL, path)


if __name__ == "__main__":
    data = latestWaterLevels()
    print(f"{len(data) if data else 0} bytes of OPW water level GeoJSON")
