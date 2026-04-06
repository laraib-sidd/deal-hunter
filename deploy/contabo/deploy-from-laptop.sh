#!/usr/bin/env bash
# Deploy deal-hunter to Contabo VPS (jarvis)
# Usage: ./deploy/contabo/deploy-from-laptop.sh
set -euo pipefail

VPS="jarvis"  # SSH alias from ~/.ssh/config
REMOTE_DIR="/opt/deal-hunter"

echo "=== Deal Hunter Deploy to $VPS ==="

# 1. Create remote directory
echo "[1/5] Creating remote directory..."
ssh "$VPS" "mkdir -p $REMOTE_DIR"

# 2. Copy docker-compose.yml
echo "[2/5] Copying docker-compose.yml..."
scp deploy/contabo/docker-compose.yml "$VPS:$REMOTE_DIR/docker-compose.yml"

# 3. Copy .env (secrets)
echo "[3/5] Copying .env..."
if [ ! -f deploy/contabo/.env ]; then
    echo "ERROR: deploy/contabo/.env not found. Copy .env.example and fill in values."
    exit 1
fi
scp deploy/contabo/.env "$VPS:$REMOTE_DIR/.env"

# 4. Copy cron + healthcheck scripts
echo "[4/5] Copying scripts..."
scp deploy/contabo/scripts/cron-run.sh "$VPS:$REMOTE_DIR/cron-run.sh"
scp deploy/contabo/scripts/healthcheck.sh "$VPS:$REMOTE_DIR/healthcheck.sh"
ssh "$VPS" "chmod +x $REMOTE_DIR/cron-run.sh $REMOTE_DIR/healthcheck.sh"

# 5. Install cron jobs
echo "[5/5] Setting up cron..."
ssh "$VPS" "cat <<'CRON' | crontab -l 2>/dev/null | grep -v deal-hunter | cat - /dev/stdin | crontab -
# deal-hunter: scrape + score every 2 hours
0 */2 * * * $REMOTE_DIR/cron-run.sh >> /var/log/deal-hunter.log 2>&1
CRON"

# Pull and test
echo ""
echo "=== Pulling image and running test... ==="
ssh "$VPS" "cd $REMOTE_DIR && docker compose pull && docker compose run --rm deal-hunter deal-hunter version"

echo ""
echo "=== Deploy complete! ==="
echo "Cron runs every 2 hours. Check logs: ssh $VPS 'tail -50 /var/log/deal-hunter.log'"
echo "Manual run: ssh $VPS 'cd $REMOTE_DIR && docker compose up'"
