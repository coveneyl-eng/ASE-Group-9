# Flood thin slice dashboard: React build + FastAPI in one image, served on :8080.
FROM node:25-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120
COPY requirements.txt .
RUN pip install --retries 5 -r requirements.txt
COPY api/ api/
COPY --from=web /web/dist web/dist
EXPOSE 8080
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080"]
