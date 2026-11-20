# Build from the repo root, for Azure (linux/amd64):
#   docker build --platform linux/amd64 -f flood-thin-slice/Dockerfile -t mregan4/thin-slice:latest .
# Run against the local compose stack (default Docker context, not Docker Desktop):
#   docker run --rm --network host -v "$PWD/flood-thin-slice/data:/app/flood-thin-slice/data" mregan4/thin-slice
# Every connection setting is an environment variable; see the top of load_all.py.
FROM python:3.12-slim
# rasterio's wheel needs libexpat, which the slim image leaves out
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY flood-thin-slice/requirements.txt flood-thin-slice/requirements.txt
RUN pip install --no-cache-dir -r flood-thin-slice/requirements.txt
COPY APIs/ APIs/
COPY flood-thin-slice/load_all.py flood-thin-slice/
WORKDIR /app/flood-thin-slice
# Big downloads land here; mount a volume (e.g. Azure Files) to keep them between runs. Optional.
RUN mkdir -p data
CMD ["python", "load_all.py"]
