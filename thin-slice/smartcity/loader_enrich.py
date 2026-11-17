"""Enrich assets with LiDAR DTM ground elevation (GeoPandas + rasterio) and archive layers in Blob Storage."""
from pathlib import Path

import geopandas as gpd
import rasterio
from azure.storage.blob import BlobServiceClient

from smartcity import config, db, telemetry

STATIC = Path(__file__).resolve().parent.parent / "static"


def sample_elevations(assets: gpd.GeoDataFrame, dtm_path: Path) -> list[float]:
    with rasterio.open(dtm_path) as dtm:
        coords = [(geom.x, geom.y) for geom in assets.geometry]
        return [round(float(v[0]), 2) for v in dtm.sample(coords)]


def upload_layers() -> list[str]:
    service = BlobServiceClient.from_connection_string(config.BLOB_CONNECTION_STRING)
    container = service.get_container_client("static-layers")
    if not container.exists():
        container.create_container()
    names = []
    for path in sorted(STATIC.iterdir()):
        with path.open("rb") as fh:
            container.upload_blob(path.name, fh, overwrite=True)
        names.append(path.name)
    return names


def main():
    t = telemetry.setup("static-loader")
    with db.connect() as conn:
        assets = gpd.read_postgis("SELECT asset_id, name, geom FROM assets", conn, geom_col="geom")
        elevations = sample_elevations(assets, STATIC / "dtm_sample.tif")
        conn.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS elevation_m double precision")
        for asset_id, elevation in zip(assets.asset_id, elevations):
            conn.execute("UPDATE assets SET elevation_m = %s WHERE asset_id = %s", (elevation, int(asset_id)))
        t["log"].info("DTM elevations: %s", dict(zip(assets.name, elevations)))
    t["log"].info("uploaded to blob static-layers: %s", upload_layers())


if __name__ == "__main__":
    main()
