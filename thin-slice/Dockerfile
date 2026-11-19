# One image for every Python agent/service. Built from the repo root so the team's API clients (APIs/)
# and static data (static/) are included:  docker compose build   (context: .., see docker-compose.yml)
FROM python:3.12-slim
# Retries and long timeouts for slow connections
RUN echo 'Acquire::Retries "10"; Acquire::http::Timeout "120"; Acquire::https::Timeout "120";' > /etc/apt/apt.conf.d/80-retries \
 && apt-get update && apt-get install -y --no-install-recommends gdal-bin osm2pgsql && rm -rf /var/lib/apt/lists/*
WORKDIR /repo/thin-slice
COPY thin-slice/requirements.txt requirements.txt
COPY APIs/notification/requirements.txt /tmp/notification-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 -r requirements.txt -r /tmp/notification-requirements.txt
COPY APIs/ /repo/APIs/
COPY static/ /repo/static/
COPY thin-slice/smartcity/ smartcity/
COPY thin-slice/static/ static/
COPY thin-slice/fixtures/ fixtures/
COPY thin-slice/loader/ loader/
ENV PYTHONUNBUFFERED=1 METRICS_PORT=9464
