# Production deploy — pin, gate, and split web from the cron job

**Status:** ready for `/go` after `/design` is not required (no new screens)
**Author:** (Laraib)
**Repo:** `~/pers/deal-hunter`
**Supersedes for execution:** the deploy story in `docs/plans/close-the-loop.md` only where it left cron on `:latest` and the dashboard off the box. The scrape cycle itself stays.

## Why

What runs today:

- Push to `main` builds `Dockerfile` and pushes `ghcr.io/laraib-sidd/deal-hunter:latest` **before** pytest (`.github/workflows/deploy.yml`). A red suite still moves `:latest`.
- The image installs `.[dev]` (pytest, ruff) and runs as root (`Dockerfile`).
- The VPS does not build. `deploy/contabo/deploy-from-laptop.sh` copies compose, `.env`, and scripts to `/opt/deal-hunter` and pulls once. Cron is `0 */2 * * * /opt/deal-hunter/cron-run.sh`.
- `cron-run.sh` is `docker compose up` with **no pull**. A new GHCR image sits unused until the laptop script runs again. Watchtower is commented out. That is the right instinct (no surprise pull) with no replacement.
- Compose has one oneshot service. `restart: "no"`. The dashboard is not on the server. GitHub Pages (`pages.yml`) publishes a static snapshot and cannot see `/data/deals.db`.
- `healthcheck.sh` ages `/var/log/deal-hunter.log` and is **not** installed in the crontab the laptop script writes. `/health` always returns 200, including `last_run: none yet`.

A production shape for this app is still one VPS, one image, one SQLite file. It is not a cluster.

## Locked decisions

1. **Stay on Contabo, Docker, GHCR, SQLite.** No Kubernetes, no second database, no Watchtower. Pages stays a snapshot and is not the live app.
2. **One image, two processes.** `web` stays up (`python -m deal_hunter.serve dash --host 0.0.0.0 --port 8001`). `run` is the cron oneshot (`deal-hunter run --ai --min-score 6 --notify`). Same image, same volume, same `.env`.
3. **The server pins a git sha.** Compose image is `${DEAL_HUNTER_IMAGE:-ghcr.io/laraib-sidd/deal-hunter}:${DEAL_HUNTER_IMAGE_TAG}`. `/opt/deal-hunter/.env` holds the tag. Rollback is setting the previous sha and `docker compose up -d web`. `:latest` may exist as a mirror of the newest sha that passed the smoke check. Cron never pulls.
4. **Tests run on the GitHub runner with uv, before any push.** The published image does not contain `tests/` or `.[dev]`. Drop `docker run --entrypoint pytest` against the published tag.
5. **Dashboard listens on loopback only.** Compose publishes `127.0.0.1:8001:8001`. Reach it through Tailscale/SSH, not the public NIC. No login screen this epic.
6. **Stale means HTTP 503.** `/health` returns 503 when `last_run_summary` is missing or `started_at` is older than 3 hours. 200 otherwise. Body stays the current plain `<pre>` text. Docker and the host script both treat non-200 as down.
7. **Automatic SSH deploy does not run until secrets exist.** A `workflow_dispatch` workflow SSHs the pinned sha. If `VPS_HOST` or `VPS_SSH_KEY` is unset, the job logs that and exits 0. It does not run on every push.
8. **Secrets stay in `/opt/deal-hunter/.env`.** Never in the image, never in the workflow logs.

## Architecture

```
push main
  → uv pytest + ruff          (job: test)
  → docker build runtime      (job: image, needs test)
  → push :$SHA
  → smoke `deal-hunter version` on that tag
  → retag :latest to that sha

human or workflow_dispatch
  → write DEAL_HUNTER_IMAGE_TAG=$SHA into server .env
  → docker compose pull
  → docker compose up -d web
  → cron keeps `compose run --rm run` on the pinned tag

web :8001 on 127.0.0.1  ──reads──►  /data/deals.db
cron every 2h `run`     ──writes─►  same file
hourly healthcheck.sh   ──curl───►  /health (503 if last run ≥ 3h) → Telegram
daily sqlite .backup    ──writes─►  /data/backups, keep 7
```

## Slice H — `/health` tells the truth

**Files:** `src/deal_hunter/dashboard/app.py`, `tests/test_dashboard/test_routes.py`

`health()` uses `last_run_summary`. No row, or `started_at` older than 3 hours (UTC), returns `HTMLResponse` status 503. A fresh row returns 200. Do not change the text format. Tests cover both.

**Test:** `uv run pytest -q tests/test_dashboard/test_routes.py`

## Slice I — Runtime image

**Files:** `Dockerfile`

Multi-stage. Builder installs the project with `uv`. Final stage is `python:3.13-slim-bookworm` with only what the app needs to import (include the lxml runtime libs, not `gcc` or the test tree). `useradd` a non-root user, `chown` `/data`, `USER` that user. `ENV DEAL_HUNTER_DB_PATH=/data/deals.db`. `ENTRYPOINT ["deal-hunter"]`. Do not `uv pip install ".[dev]"`. Do not `COPY tests`.

**Test:** `docker build -t deal-hunter:dev . && docker run --rm deal-hunter:dev version`

## Slice C — CI gate

**Files:** `.github/workflows/deploy.yml`
**Blocked by:** I (the image no longer has pytest).

Jobs:

1. `test` — `uv sync` and `uv run pytest -q` and `uv run ruff check src/`.
2. `image` — `needs: test`. Build and push **only** `ghcr.io/laraib-sidd/deal-hunter:${{ github.sha }}`.
3. Smoke — `docker run --rm ghcr.io/laraib-sidd/deal-hunter:${{ github.sha }} version`. On success, retag that sha as `:latest` and push the tag. Do not retag if smoke fails.

**Test:** `uv run python -c "import yaml,pathlib; d=yaml.safe_load(pathlib.Path('.github/workflows/deploy.yml').read_text()); assert 'test' in d['jobs'] and d['jobs']['image']['needs']=='test'"`

## Slice D — Compose topology

**Files:** `deploy/contabo/docker-compose.yml`, `deploy/contabo/.env.example`
**Blocked by:** H (healthcheck expects non-200 when stale).

Services:

- `web` — image pinned by `DEAL_HUNTER_IMAGE_TAG`, `restart: unless-stopped`, command `python -m deal_hunter.serve dash --host 0.0.0.0 --port 8001`, ports `127.0.0.1:8001:8001`, volume `deal-hunter-data:/data`, `env_file: .env`, healthcheck `curl -f http://127.0.0.1:8001/health` (install `curl` in the runtime image — that is a one-line note for slice I; if I has already shipped without curl, D’s healthcheck uses `python -c` urllib so I does not need a rebuild solely for curl). Prefer the python probe so I and D stay independent.
- `run` — same image, volume, env. `restart: "no"`. `profiles: ["run"]` or a service that cron starts with `docker compose run --rm run`. Command stays `deal-hunter run --ai --min-score 6 --notify`. No published ports.

`.env.example` documents `DEAL_HUNTER_IMAGE_TAG` (required on the server) and states the dashboard is loopback-only.

**Test:** `DEAL_HUNTER_IMAGE_TAG=test docker compose -f deploy/contabo/docker-compose.yml config`

## Slice R — Rollout, cron, backup

**Files:** `deploy/contabo/deploy-from-laptop.sh`, `deploy/contabo/scripts/cron-run.sh`, `deploy/contabo/scripts/healthcheck.sh`, `deploy/contabo/scripts/backup-db.sh`, `.github/workflows/rollout.yml`
**Blocked by:** D and C (service names `web`/`run`, image workflow name `Build & Deploy`).

- Laptop script takes `IMAGE_TAG` (default: current git sha), writes or replaces `DEAL_HUNTER_IMAGE_TAG` in the remote `.env` without printing secrets, `docker compose pull`, `docker compose up -d web`.
- Cron line stays every 2 hours but the script becomes `docker compose run --rm run` in `/opt/deal-hunter`. It does not pull.
- Install `healthcheck.sh` hourly. It curls `http://127.0.0.1:8001/health`. Non-200 sends the existing Telegram message and exits 1. Stop using log mtime as the signal.
- `backup-db.sh` runs daily: `docker compose exec -T web python -c` or `sqlite3` inside the container to `.backup` `/data/backups/deals-<utcdate>.db`, delete backups older than 7 days. Cron `15 3 * * *`.
- `rollout.yml` is `workflow_dispatch` with input `sha`. If `secrets.VPS_HOST` or `secrets.VPS_SSH_KEY` is empty, log `rollout skipped: secrets not set` and exit 0. Otherwise SSH and run the same pull / `up -d web` as the laptop script, exporting `IMAGE_TAG` from the input (default `github.sha`).

**Test:** `bash -n deploy/contabo/deploy-from-laptop.sh deploy/contabo/scripts/cron-run.sh deploy/contabo/scripts/healthcheck.sh deploy/contabo/scripts/backup-db.sh`

## Gotchas

- The existing Docker volume was created by a root container. The non-root user in slice I will get `attempt to write a readonly database` until the first deploy does `docker run --rm -v deal-hunter-data:/data alpine chown -R <uid>:<uid> /data`. Put that chown in the laptop script and the rollout workflow once, not in every cron run.
- `compose config` fails if `DEAL_HUNTER_IMAGE_TAG` is unset. The example file and both deploy paths set it. Do not default the tag to `latest` inside compose.
- `/health` 503 makes the dashboard look “unhealthy” for the first 3 hours after a fresh volume, before the first `run`. That is the intended signal. Do not special-case it back to 200.
- `workflow_dispatch` exit 0 when secrets are missing is so a merge does not go red. It is not a successful deploy. The log line is the contract.
- Do not print `.env` in SSH scripts (`set -x` is forbidden in those scripts).
- SQLite backups must not use `cp` of a live file. Use the sqlite backup API.

## Done

- `uv run pytest -q tests/test_dashboard/test_routes.py tests/test_cli/test_cycle.py` is green, and `uv run ruff check src/` is clean.
- `docker compose -f deploy/contabo/docker-compose.yml config` with `DEAL_HUNTER_IMAGE_TAG=test` shows services `web` and `run`, and `web` publishes `127.0.0.1:8001` only.
- `deploy.yml` has a `test` job that `image` needs, and the push tags include the commit sha.
- A missing last run returns HTTP 503 from `/health`.
- Cron script does not contain `docker compose pull`.

## Waves

| Wave | Beads | Why together |
|---|---|---|
| 1 | H health, I image | No shared files. |
| 2 | C CI, D compose | C waits on the runtime image. D waits on the health contract. They do not share files. |
| 3 | R rollout | Calls the service names from D and the workflow name from C. |

## Out of scope

Kubernetes, a managed database, Watchtower, public dashboard auth, changing the scrape/score cycle, and turning GitHub Pages into the live app.
