#!/usr/bin/env bash
# Demo entry point: runs the end-to-end verifier inside the compose network, then the Postman API suite.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports
docker compose run --rm --no-deps \
  -e MQTT_USERNAME=sensor -e MQTT_PASSWORD=sensor-pass \
  -e VERIFY_REPORT=/app/reports/thin-slice-junit.xml -v "$PWD/reports:/app/reports" \
  sensor-sim python -m smartcity.verify
npx --yes newman run postman/smartcity.postman_collection.json --insecure \
  --reporters cli,junit --reporter-junit-export reports/postman-junit.xml
