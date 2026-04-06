#!/usr/bin/env bash
# Deploy deal-hunter to Contabo VPS
# Usage: VPS_IP=<tailscale-ip> ./deploy/contabo/deploy-from-laptop.sh
set -euo pipefail

if [ -z "${VPS_IP:-}" ]; then
    echo "ERROR: VPS_IP not set."
    echo "  Usage: VPS_IP=100.64.0.5 ./deploy/contabo/deploy-from-laptop.sh"
    exit 1
fi

REMOTE_DIR="/opt/deal-hunter"
SSH_OPTS="-o StrictHostKeyChecking=no"
SSH_TARGET="root@${VPS_IP}"

echo "=== Deal Hunter Deploy to ${VPS_IP} ==="

# 1. Create remote directory
echo "[1/5] Creating remote directory..."
ssh $SSH_OPTS "$SSH_TARGET" "mkdir -p $REMOTE_DIR"

# 2. Copy docker-compose.yml
echo "[2/5] Copying docker-compose.yml..."
scp $SSH_OPTS deploy/contabo/docker-compose.yml "$SSH_TARGET:$REMOTE_DIR/docker-compose.yml"

# 3. Copy .env (secrets)
echo "[3/5] Copying .env..."
if [ ! -f deploy/contabo/.env ]; then
    echo "ERROR: deploy/contabo/.env not found. Copy .env.example and fill in values."
    exit 1
fi
scp $SSH_OPTS deploy/contabo/.env "$SSH_TARGET:$REMOTE_DIR/.env"

# 4. Copy cron + healthcheck scripts
echo "[4/5] Copying scripts..."
scp $SSH_OPTS deploy/contabo/scripts/cron-run.sh "$SSH_TARGET:$REMOTE_DIR/cron-run.sh"
scp $SSH_OPTS deploy/contabo/scripts/healthcheck.sh "$SSH_TARGET:$REMOTE_DIR/healthcheck.sh"
ssh $SSH_OPTS "$SSH_TARGET" "chmod +x $REMOTE_DIR/cron-run.sh $REMOTE_DIR/healthcheck.sh"

# 5. Install cron jobs (append without duplicating)
echo "[5/5] Setting up cron..."
ssh $SSH_OPTS "$SSH_TARGET" "
(crontab -l 2>/dev/null | grep -v deal-hunter; echo '# deal-hunter: scrape + score every 2 hours
0 */2 * * * $REMOTE_DIR/cron-run.sh >> /var/log/deal-hunter.log 2>&1') | crontab -
"

# Pull and test
echo ""
echo "=== Pulling image and running test... ==="
ssh $SSH_OPTS "$SSH_TARGET" "cd $REMOTE_DIR && docker compose pull && docker compose run --rm deal-hunter deal-hunter version"

echo ""
echo "=== Deploy complete! ==="
echo "Cron runs every 2 hours. Logs: ssh root@${VPS_IP} 'tail -50 /var/log/deal-hunter.log'"
echo "Manual run: ssh root@${VPS_IP} 'cd $REMOTE_DIR && docker compose up'"
