#!/usr/bin/env bash
# Hourly health check via the dashboard /health endpoint.
set -euo pipefail

HEALTH_URL="http://127.0.0.1:8001/health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    echo "OK: /health returned 200"
    exit 0
fi

if [ -f /opt/deal-hunter/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source /opt/deal-hunter/.env
    set +a
fi

if [ -n "${DEAL_HUNTER_TELEGRAM__BOT_TOKEN:-}" ] && [ -n "${DEAL_HUNTER_TELEGRAM__CHAT_ID:-}" ]; then
    curl -s "https://api.telegram.org/bot${DEAL_HUNTER_TELEGRAM__BOT_TOKEN}/sendMessage" \
        -d "chat_id=${DEAL_HUNTER_TELEGRAM__CHAT_ID}" \
        -d "text=⚠️ deal-hunter /health returned HTTP ${HTTP_CODE} (expected 200). Check: ssh jarvis 'cd /opt/deal-hunter && docker compose logs web'" \
        > /dev/null
fi

echo "WARNING: /health returned HTTP ${HTTP_CODE}"
exit 1
