# PostgreSQL 16 + PostGIS + pgRouting + TimescaleDB in one image (Azure: Flexible Server with the same extensions).
FROM postgis/postgis:16-3.5
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates lsb-release postgresql-16-pgrouting \
 && echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/timescaledb.list \
 && curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg \
 && apt-get update && apt-get install -y --no-install-recommends timescaledb-2-postgresql-16 \
 && rm -rf /var/lib/apt/lists/*
COPY init/ /docker-entrypoint-initdb.d/
CMD ["postgres", "-c", "shared_preload_libraries=timescaledb"]
