#!/usr/bin/env bash
# Wait until the static-layer loader has finished loading the map data, then let the agents settle.
# Works whether the loader is still running or has already exited (docker compose wait only sees running ones).
set -euo pipefail
cd "$(dirname "$0")/.."
for _ in $(seq 1 90); do
  id=$(docker compose ps -aq static-loader)
  if [ -n "$id" ]; then
    read -r state code <<<"$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$id")"
    if [ "$state" = "exited" ]; then
      if [ "$code" != "0" ]; then
        echo "static-loader failed (exit $code):"; docker compose logs --no-color static-loader | tail -40; exit 1
      fi
      echo "static layers loaded; letting agents settle"; sleep 20; docker compose ps -a; exit 0
    fi
  fi
  sleep 5
done
echo "timed out after 7.5 min waiting for static-loader"; docker compose ps -a; exit 1
