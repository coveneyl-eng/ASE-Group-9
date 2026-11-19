# PostgreSQL 16 + PostGIS + pgRouting + TimescaleDB in one image (Azure: Flexible Server with the same extensions).
# Built on the official postgres image because it exists for both Intel (amd64) and Apple-chip (arm64) machines;
# postgis/postgis is published for amd64 only.
FROM postgres:16-bookworm

# PostGIS + pgRouting from the PostgreSQL apt repository the base image already trusts
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-postgis-3 postgresql-16-pgrouting \
 && rm -rf /var/lib/apt/lists/*

# TimescaleDB from Timescale's own repository. If no package exists for this CPU, carry on without it:
# the schema then uses plain tables and the dashboard shows the database as "degraded" instead of failing.
RUN (apt-get update \
     && apt-get install -y --no-install-recommends curl gnupg ca-certificates lsb-release \
     && echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/timescaledb.list \
     && curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg \
     && apt-get update && apt-get install -y --no-install-recommends timescaledb-2-postgresql-16) \
    || echo "TimescaleDB not available for this platform; continuing without it" \
 ; rm -rf /var/lib/apt/lists/*

COPY init/ /docker-entrypoint-initdb.d/
# Preload TimescaleDB only when it was installed, so the server always starts.
CMD ["sh", "-c", "if [ -f /usr/lib/postgresql/16/lib/timescaledb.so ]; then exec docker-entrypoint.sh postgres -c shared_preload_libraries=timescaledb; else exec docker-entrypoint.sh postgres; fi"]
