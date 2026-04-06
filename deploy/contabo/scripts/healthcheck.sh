#!/usr/bin/env bash
# Check if deal-hunter ran recently (within last 3 hours).
# Alert via Telegram if it hasn't.
set -euo pipefail

LOG="/var/log/deal-hunter.log"
MAX_AGE_HOURS=3

if [ ! -f "$LOG" ]; then
    echo "No log file found — deal-hunter may not have run yet."
    exit 0
fi

last_modified=$(stat -c %Y "$LOG" 2>/dev/null || stat -f %m "$LOG" 2>/dev/null)
now=$(date +%s)
age_hours=$(( (now - last_modified) / 3600 ))

if [ "$age_hours" -ge "$MAX_AGE_HOURS" ]; then
    # Load env for Telegram creds
    if [ -f /opt/deal-hunter/.env ]; then
        source /opt/deal-hunter/.env
    fi

    if [ -n "${DEAL_HUNTER_TELEGRAM__BOT_TOKEN:-}" ] && [ -n "${DEAL_HUNTER_TELEGRAM__CHAT_ID:-}" ]; then
        curl -s "https://api.telegram.org/bot${DEAL_HUNTER_TELEGRAM__BOT_TOKEN}/sendMessage" \
            -d "chat_id=${DEAL_HUNTER_TELEGRAM__CHAT_ID}" \
            -d "text=⚠️ deal-hunter hasn't run in ${age_hours}h. Check: ssh jarvis 'tail -20 /var/log/deal-hunter.log'" \
            > /dev/null
    fi

    echo "WARNING: deal-hunter last ran ${age_hours}h ago"
    exit 1
fi

echo "OK: deal-hunter last ran ${age_hours}h ago"
