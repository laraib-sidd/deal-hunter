# Deal Hunter v2 — Execution-Ready Plan

**Status:** DRAFT for approval (pers ritual: plan-first, no code touched yet)
**Author:** (Laraib)
**Repo:** `~/pers/deal-hunter`
**Goal:** Go from "filter-and-score scraper" to a closed-loop **price-intelligence system**:
sources → data → intelligence → **live dashboard + interactive Telegram chat bot (+ auto-push)**.

---

## 0. Locked decisions (reflect these as constraints; do NOT revisit)

1. **Delivery layer (user-confirmed):** an **interactive Telegram chat bot** I can DM
   ("3060 under 15k in Delhi") that replies **live**, **AND** auto-pushes alerts the moment a
   **new** matching listing is ingested. Plus a **user dashboard**.
2. **Stack stays Python/`uv`/`sqlmodel`/SQLite** (keeps current deps; self-contained on the VPS
   container — no new infra). Add **`fastapi` + `uvicorn` + `jinja2` + `python-telegram-bot`**
   (+ `playwright` for OLX/optional). No React SPA — dashboard is server-rendered HTML+HTMX.
3. **Near-instant, honestly:** none of the sources expose push webhooks. "Replies as soon as a
    listing is listed" = **high-frequency poll loop** that raises an alert the moment an
    **unseen fingerprint** is ingested. Honest latency ceiling: ~1-3 min for Reddit/TechEnclave,
    ~5-15 min for OLX (see 1A).
4. **Deployment:** stays on the Contabo VPS container (existing Docker + cron). One long-running
   `serve` process runs FastAPI dashboard + bot + poll loop.
5. Never put secrets in code. `.env` only, gitignored. Real prices only — no fabricated data.
6. **Scope of "deal":** still hardware-first for scoring, but source layer may ingest coupons/
   travel/etc. and tag them `category=other` (they surface in dashboard, not in hardware alerts
   unless a watch matches).

---

## Phase 1 — SOURCES (figure out all of them)

### 1A. Source matrix (feasibility-ranked, verified against live research)

| # | Source | Type | Feasibility | Method | Alert latency |
|---|--------|------|-------------|--------|---------------|
| S1 | **Reddit** (existing) | peer listings | ✅ **Write now** | PRAW `new()` per sub + deal subs | ~1-3 min |
| S2 | **TechEnclave** (existing) | forum | ✅ **Write now** | httpx Discourse API categories | ~3-5 min |
| S3 | **OLX.in** | classifieds | ⚠️ **Playwright** needed | headless browser; search urls per city+cat; Cloudflare-challenged | ~5-15 min |
| S4 | **Facebook Marketplace** | classifieds | 🔒 **Anti-bot wall** | login + fingerprinting since 2026; anonymous access tightened | n/a without session |
| S5 | **Retail new-price baseline** (Computify, MDComputers, TheITDepot, Amazon DL) | MSRP re-center | ✅ cheap | static fetch of current new prices | n/a (daily) |
| S6 | **Discord/Telegram deal channels** | chat | ⚠️ **to research** | no public search; needs invited session. **BLOCKED ON:** access. |

**Findings surfaced (do not pretend these are easy):**
- **OLX** is behind **Cloudflare bot protection** (verified). Will need `playwright` + stealth.
  Pending on a test that the VPS IP isn't challenged outright.
- **Facebook Marketplace** has **aggressive anti-bot**: tightening in 2026, login walls,
  fingerprinting (verified via Scrapfly/Reddit). **BLOCKED ON:** a logged-in session that must
  be refreshed; mark `status=broken` if session dies. Plan builds the adapter shell now, wires
  it but treats it as **best-effort**.
- No source has real webhooks → instant = poll, as decided.

### 1B. New scraper interface contract
```python
# src/deal_hunter/scrapers/base.py  (extend)
class BaseScraper(abc.ABC):
    source_name: str
    freshness_window_seconds: int   # how stale the "new" curve is
    async def scrape(...) -> list[Listing]          # existing
    async def scrape_new_only(...) -> list[Listing] # filter to not-yet-seen already at source if cheap
```
Each adapter returns `Listing` with a **new `source_item_id`** separate from the cross-source
`fingerprint` (a given FB post and Reddit post of the same card still dedupe into one listing,
but they are two distinct *offers*).

- New files: `src/deal_hunter/scrapers/olx.py`, `facebook.py`, `retail_baseline.py`.
- `runner.py`: add a `FAST_SOURCES` (S1,S2 → polled every 2 min in `serve`) vs
  `HEAVY_SOURCES` (S3,S4 → compacted ≤ every 10-15 min, disabled unless opted-in).

---

## Phase 2 — Data organization (write & read)

### 2A. Schema (sqlmodel models; one migration via sqlmodel + a small `migrate` step)

**`Listing` (existing) — keep, add columns:**
```
source_id         (was `str`)  -> THE authoritative offer id (per-source unique)
fingerprint       existing      -> cross-source dedup key (title|price|loc)
status            str default 'active'   ('active'|'stale'|'dead'|'suppressed')
seller_id         int | None FK -> sellers
times_seen        int default 1           # increments each scrape (dead if N>X and price↑)
last_confirmed_at datetime|None           # last scrape it still surfaced
```
ADD INDEX `(fingerprint)` unique? yes; `(source, source_id)` unique; `(status, last_confirmed_at)`.

**NEW `Seller`** (`src/deal_hunter/db/models.py`)
```python
class Seller(SQLModel, table=True):
    __tablename__ = "sellers"
    id, source, source_key(str, index), display_name, url,
    first_seen_at, last_seen_at,
    listing_count:int=0, flagged_count:int=0, avg_pct_below_mid: float|None,
    is_suspect:bool=False, notes:str|None
    UNIQUE(source, source_key)
```

**NEW `WatchRule`** (persistent buy-intent)
```
`WatchRule`: id, label, enabled, kind ('price'|'query'), 
   query(str) e.g. "rtx 3060 ti", category, min_score int, max_price float|None,
   locations(list[str]), alert_on_newest bool default True, created_at
```
`WatchHit`: id, rule_id, listing_id, score_at, alerted_at

**`PriceSnapshot` / `price_history` (existing)** — keep writing on every newly-scored listing; it
is now the raw matrix for the live baseline. Add `index (canonical_name, observed_at)`.

### 2B. Write path (single Writer)
- `IngestionService.write(listings)`: upsert by `(source, source_id)`; if new → create/exists
  `Listing` AND upsert `Seller`; if existing but was marked `dead` and re-listed → flip to
  `active`; always bump `times_seen` + `last_confirmed_at`.
- After upsert, delegate NEW listings to the scorer and to alerts.

### 2C. Read path
- Repos `db/repo_listings.py`, `repo_market.py`, `repo_watch.py`, `repo_seller.py` isolation:
  **query builder → models → nothing else**. Signatures below in Phase 3/4 code.

---

## Phase 3 — Intelligence (closed-loop)

### 3A. Live market baseline (the core upgrade)
- On each score, `MarketStat` computed per canonical:
  `median, p25, p75, n, timespan` from last-60-day `price_history`.
- `estimate_fair_value` becomes **weighted**: `fair = 0.5*model(msrp,age) + 0.5*rolling_median`
  (config in `config.py`: `baseline_weights`). `price_vs_fair_pct` now vs this blended fair, not
  the raw model.
- New signal `market_percentile` = percentile of asking within its own live distribution.

### 3B. Deal velocity / freshness
- `velocity_score`: dock if `age <24h` (fresh is good), penalize if same listing `times_seen>N`
  or `status` still active at a "too good" price for `>Xh` (→ likely stale / scam).
- New high signal: **"price cut vs first-seen"** — if a listing's price drops across scrapes,
  surface it.

### 3C. Scam/risk strengthen (add to `red_flags.py`)
- Reuse seller identity: `flag if seller.is_suspect`.
- Flag a price that is `> age-scoped discount` **and** the listing has sat `>72h` unsold.
- Confirmed via live data only. **`BLOCKED ON:`** no open scam-report DB; rely on pattern.

### 3D. Watch matching
- `Matcher` evaluates each NEW listing against enabled `WatchRule`s → creates `WatchHit`,
  sets `alert_on_match` → push via bot.

### 3E. Files
`analysis/baseline.py` (MarketStat), `analysis/velocity.py`, extend `scorer.py` to call them
and accept `baseline_weights`. All pure functions → unit-testable without DB (pip pytest).

---

## Phase 4 — Telegram bot (interactive + auto-push)

**Lib:** `python-telegram-bot` (async). Entry: `serve.py`.

### 4.1 Interactive commands (user DMs the bot)
- `/help`
- **Free-text query:** send `"rtx 3060 under 15000 in Delhi"` → NL-ish parser
  (`query_parser.py`) → `(keywords, max_price, locations)` → search repo → return top 5
  ranked, each with an inline **Open** action button.
- `/watch rtx 3060 under 15k in delhi` → creates `WatchRule`, replies ack.
- `/watches` — list, `/unwatch <id>`, `/pause <id>`.
- Inline result message buttons: **Open**, **Not interesting (suppress)**, **Mark bought**
  → update `Listing.status` / seller.

### 4.2 Auto-push
- Push loop hourly-rebuilt on `IngestService` NEW events: for each NEW listing that satisfies
  a `WatchRule` OR scores `>= deal_alert_min` → send `send_deal_alert` (existing formatter,
  extended to include `market_baseline` and `seller` line). Rate-limit: max N/min, dedup by
  fingerprint + sometimes cooldown per canonical.

### 4.3 Tests
`tests/test_bot/test_query_parser.py`, `test_command_*`, `test_bot_push_trigger.py`
(httpx-compatible fake PTB, no real send).

---

## Phase 5 — Dashboard (server-rendered, FastAPI+HTMX)

Routes (FastAPI app in `serve.py` or `dashboard/app.py`):
- `GET /` — cards: `scraped_24h`, `active_deals`, `avg_latency`, `sources_health`, `active_watches`
- `GET /deals` — table, filters (verdict, source, category, price range, fresh).
- `GET /product/{canonical}` — **price-history chart** (Chart via small inline SVG; no CDN) + current
  live baseline + related listings + seller risk strip.
- `GET /watch` — watch CRUD + hit log.
- `GET /seller/{id}` — seller profile, listings, flag history.
- `GET /health` — per-source pulse (JSON, for `/health` bot cmd + dashboard card).
Serves on `:8001` publically on VPS behind a simple proxy; auth via `X-Auth` single code in .env
(empty → bind to 127.0.0.1 only).

---

## Phase 6 — Deployment / `serve`

- `scripts/deploy_dashboard.sh` (or extend existing deploy): builds multi-`--target` image:
  - `ingest` cron: existing `deal-hunter watch`→ replaced by interval runner
  - `serve` long-lived: `uvicorn dashboard.app:app` + bot polling concurrently
- SMOKE check after redeploy (see Verify).

---

## Verification per phase (exact commands; run in-repo)

```bash
cd ~/pers/deal-hunter
env -u VIRTUAL_ENV -u PYTHONPATH uv run pytest -q          # all green, expect ~75 + new
env -u VIRTUAL_ENV -u PYTHONPATH uv run ruff check src/
env -u VIRTUAL_ENV -u PYTHONPATH uv run ruff format src/
```

### Per-adapter verification (source reality, not mocks)
- S1/S2: `./src cli scrape --source reddit` and `--source techenclave` return listings
- S3: `./scrape_olx_probe.py` (scratch) returns ≥1 real listing w/o Cloudflare challenge;
  else mark `OLX_BLOCKED=1` and log it.
- S5: `src/retail_baseline.py --dry` pulls ≥1 MSRP for a tracked SKU.
- Bot: `python -m pytest -q tests/test_bot` + manual `/start` shows menu
- Dashboard: `curl -fsS localhost:8001` → 200; `curl -fsS localhost:8001/product/rtx-3060` → 200

Each phase must pass its gate before the next starts. Don't merge to main; open focused
commits and PRs labelled (`DEALHUNTER`).

---

## Done-Definition (the worker must produce ALL of)
1. All 75 existing + new tests pass under the `env -u` command; ruff clean.
2. S1/S2/S5 live adapters return real data (OLX/S4 marked `blocked` with clear logs if not).
3. `serve` runs `dashboard` + bot in ONE process; `curl` on all routes 200.
4. DM'ing the bot `"3060 under 15k in Delhi"` returns real ranked results including liveBaseline.
5. A **new** listing (seeded test or real) triggers a push alert with rating, baseline, seller
   info; dedup stops repeats.
6. `Seller` rows populate on ingest; a `flagged` seller shows on its listing + profile.
7. Live market baseline is used in scoring (weight=0.5), visible in dashboard product page.
8. Update `docs/knowledge/pers-knowledge.md` + `CHANGELOG.md` (per ritual). Commit focused.

---

## BLOCKED ON / open
- **S4 (Facebook):** persistent logged-in session and anti-bot refresh — cannot be validated
  headless-anon. Building shell + best-effort now; flag as degraded.
- **OLX Cloudflare:** needs a live test; if challenged, feature-flag-protect.
- **Retail baseline** needs a current-price source that's cheap/reliable (Computify first).
  We'll try before Phase 6.
- **"Instant"** is bounded by poll frequency (no push hooks available publicly). Honest
  ceiling: ~1-3 min for S1/S2, ~5-15 min for OLX.

---

## Suggested execution order (worker)
P1a (S1/S2 wiring+source_id) → P2 (schema+sales+mtime) → P3A/3B baseline/velocity →
P3D (watch) → P5 (dashboard) → P4 (bot) → P6 (deploy/verify). Each cuts with focused tests.