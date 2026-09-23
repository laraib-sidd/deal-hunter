#!/usr/bin/env bash
# Daily SQLite backup using the backup API (not cp of a live file).
set -euo pipefail

cd /opt/deal-hunter

docker compose exec -T web python -c "
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

src = os.environ.get('DEAL_HUNTER_DB_PATH', '/data/deals.db')
backup_dir = Path('/data/backups')
backup_dir.mkdir(parents=True, exist_ok=True)

utc_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
dst = backup_dir / f'deals-{utc_date}.db'

src_conn = sqlite3.connect(src)
dst_conn = sqlite3.connect(dst)
src_conn.backup(dst_conn)
dst_conn.close()
src_conn.close()

cutoff = time.time() - 7 * 86400
for backup in backup_dir.glob('deals-*.db'):
    if backup.stat().st_mtime < cutoff:
        backup.unlink()
"
