# Build from the repo root: docker build -f flood-thin-slice/Dockerfile -t mregan4/thin-slice:latest .
# Run against the compose stack: docker run --rm --network host -v "$PWD/flood-thin-slice/data:/app/flood-thin-slice/data" mregan4/thin-slice
FROM python:3.12-slim
# rasterio's bundled GDAL needs libexpat, which the slim image leaves out
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY flood-thin-slice/requirements.txt flood-thin-slice/requirements.txt
RUN pip install --no-cache-dir -r flood-thin-slice/requirements.txt
COPY APIs/ APIs/
COPY flood-thin-slice/load_all.py flood-thin-slice/
WORKDIR /app/flood-thin-slice
CMD ["python", "load_all.py"]
