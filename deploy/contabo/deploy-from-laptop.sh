#!/usr/bin/env bash
# Deploy deal-hunter to Contabo VPS
# Usage: VPS_IP=<tailscale-ip> [IMAGE_TAG=<sha>] ./deploy/contabo/deploy-from-laptop.sh
set -euo pipefail

if [ -z "${VPS_IP:-}" ]; then
    echo "ERROR: VPS_IP not set."
    echo "  Usage: VPS_IP=100.64.0.5 ./deploy/contabo/deploy-from-laptop.sh"
    exit 1
fi

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"
REMOTE_DIR="/opt/deal-hunter"
SSH_OPTS="-o StrictHostKeyChecking=no"
SSH_TARGET="root@${VPS_IP}"

echo "=== Deal Hunter Deploy to ${VPS_IP} (tag: ${IMAGE_TAG}) ==="

echo "[1/6] Creating remote directory..."
ssh $SSH_OPTS "$SSH_TARGET" "mkdir -p $REMOTE_DIR"

echo "[2/6] Copying docker-compose.yml..."
scp $SSH_OPTS deploy/contabo/docker-compose.yml "$SSH_TARGET:$REMOTE_DIR/docker-compose.yml"

echo "[3/6] Copying .env..."
if [ ! -f deploy/contabo/.env ]; then
    echo "ERROR: deploy/contabo/.env not found. Copy .env.example and fill in values."
    exit 1
fi
scp $SSH_OPTS deploy/contabo/.env "$SSH_TARGET:$REMOTE_DIR/.env"

echo "[4/6] Copying scripts..."
scp $SSH_OPTS deploy/contabo/scripts/cron-run.sh "$SSH_TARGET:$REMOTE_DIR/cron-run.sh"
scp $SSH_OPTS deploy/contabo/scripts/healthcheck.sh "$SSH_TARGET:$REMOTE_DIR/healthcheck.sh"
scp $SSH_OPTS deploy/contabo/scripts/backup-db.sh "$SSH_TARGET:$REMOTE_DIR/backup-db.sh"
ssh $SSH_OPTS "$SSH_TARGET" "chmod +x $REMOTE_DIR/cron-run.sh $REMOTE_DIR/healthcheck.sh $REMOTE_DIR/backup-db.sh"

echo "[5/6] Setting up cron..."
ssh $SSH_OPTS "$SSH_TARGET" "
(crontab -l 2>/dev/null | grep -v deal-hunter; cat <<'CRON'
# deal-hunter: scrape + score every 2 hours
0 */2 * * * /opt/deal-hunter/cron-run.sh >> /var/log/deal-hunter.log 2>&1
# deal-hunter: health check hourly
0 * * * * /opt/deal-hunter/healthcheck.sh >> /var/log/deal-hunter-health.log 2>&1
# deal-hunter: daily sqlite backup
15 3 * * * /opt/deal-hunter/backup-db.sh >> /var/log/deal-hunter-backup.log 2>&1
CRON
) | crontab -
"

echo "[6/6] Pinning image tag and starting web..."
ssh $SSH_OPTS "$SSH_TARGET" "REMOTE_DIR='$REMOTE_DIR' IMAGE_TAG='$IMAGE_TAG' bash -s" <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"

if grep -q '^DEAL_HUNTER_IMAGE_TAG=' .env 2>/dev/null; then
    sed -i "s/^DEAL_HUNTER_IMAGE_TAG=.*/DEAL_HUNTER_IMAGE_TAG=${IMAGE_TAG}/" .env
else
    printf 'DEAL_HUNTER_IMAGE_TAG=%s\n' "$IMAGE_TAG" >> .env
fi

if [ ! -f .volume-chowned ]; then
    docker run --rm -v deal-hunter_deal-hunter-data:/data alpine chown -R 1000:1000 /data
    touch .volume-chowned
fi

docker compose pull
docker compose up -d web
REMOTE

echo ""
echo "=== Deploy complete! ==="
echo "Image tag: ${IMAGE_TAG}"
echo "Cron runs every 2 hours. Logs: ssh root@${VPS_IP} 'tail -50 /var/log/deal-hunter.log'"
echo "Manual run: ssh root@${VPS_IP} 'cd $REMOTE_DIR && docker compose run --rm run'"
