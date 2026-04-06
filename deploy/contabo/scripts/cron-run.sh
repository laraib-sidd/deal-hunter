#!/usr/bin/env bash
# Triggered by cron every 2 hours. Runs the full pipeline in Docker.
set -euo pipefail

cd /opt/deal-hunter

echo "=== [$(date)] deal-hunter cron start ==="

# Run scrape + score + notify in a fresh container
docker compose up --abort-on-container-exit 2>&1

echo "=== [$(date)] deal-hunter cron end ==="
