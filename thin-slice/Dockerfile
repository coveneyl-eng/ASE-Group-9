# One image for every Python agent/service. Built from the repo root so the team's API clients (APIs/)
# and static data (static/) are included:  docker compose build   (context: .., see docker-compose.yml)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin osm2pgsql && rm -rf /var/lib/apt/lists/*
WORKDIR /repo/thin-slice
COPY thin-slice/requirements.txt requirements.txt
COPY APIs/notification/requirements.txt /tmp/notification-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r /tmp/notification-requirements.txt
COPY APIs/ /repo/APIs/
COPY static/ /repo/static/
COPY thin-slice/smartcity/ smartcity/
COPY thin-slice/static/ static/
COPY thin-slice/fixtures/ fixtures/
COPY thin-slice/loader/ loader/
ENV PYTHONUNBUFFERED=1 METRICS_PORT=9464
