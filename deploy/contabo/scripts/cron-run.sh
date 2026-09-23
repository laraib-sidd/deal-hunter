#!/usr/bin/env bash
# Triggered by cron every 2 hours. Runs the pipeline in a one-shot container.
set -euo pipefail

cd /opt/deal-hunter

echo "=== [$(date)] deal-hunter cron start ==="
docker compose run --rm run
echo "=== [$(date)] deal-hunter cron end ==="
