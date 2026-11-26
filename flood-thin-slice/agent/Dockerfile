# Flood Detector agent: a small, always-on container (no GDAL, no geopandas).
# Build from the repo root, for Azure (linux/amd64):
#   docker build --platform linux/amd64 -t mregan4/flood-agent:latest flood-thin-slice/agent
# Run against the local compose stack:
#   docker run --rm --network host mregan4/flood-agent
# Same env vars as load_all.py (DB_URL, KAFKA, KAFKA_TOPIC, KAFKA_SASL_*); see the top of flood_agent.py.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY flood_agent.py .
CMD ["python", "flood_agent.py"]
