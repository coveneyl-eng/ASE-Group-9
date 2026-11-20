#!/usr/bin/env bash
# Static layer loader (an AKS CronJob in production): GDAL/ogr2ogr + osm2pgsql into PostGIS,
# then GeoPandas + rasterio enrichment and upload of the source layers to Blob Storage.
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${DATABASE_URL:-postgresql://smartcity:smartcity@localhost:5432/smartcity}"

echo "[loader] ogr2ogr: assets, CFRAM extents, road graph"
ogr2ogr -f PostgreSQL "PG:${DB}" static/assets.geojson        -nln assets        -overwrite -lco GEOMETRY_NAME=geom -lco FID=fid
ogr2ogr -f PostgreSQL "PG:${DB}" static/cfram_extents.geojson -nln cfram_extents -overwrite -lco GEOMETRY_NAME=geom -lco FID=fid
ogr2ogr -f PostgreSQL "PG:${DB}" static/road_edges.geojson    -nln road_edges    -overwrite -lco GEOMETRY_NAME=geom -lco FID=fid

echo "[loader] osm2pgsql: OSM base layer"
osm2pgsql --create --database "${DB}" --style "${OSM2PGSQL_STYLE:-/usr/share/osm2pgsql/default.style}" \
    --prefix osm static/dublin_sample.osm

echo "[loader] GeoPandas + rasterio: sample LiDAR DTM elevation at each asset, upload layers to Blob"
python -m smartcity.loader_enrich
echo "[loader] done"
