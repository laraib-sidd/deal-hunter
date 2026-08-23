# Deal Hunter — Milestones & Task Board

**Author:** (Laraib)
**Purpose:** A living task board consolidating the SE-principles audit (`se-principles-audit.md`),
the hardware scale-up plan (`hardware-scale-up.md`), and the used-market research
(`research/second-hand-buys.md`) into ordered, verifiable milestones. Refactoring continues
incrementally per software-engineering principles; each task ships green (tests + ruff) and
does NOT change user behavior unless the task says otherwise.

**Status legend:** `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

## M0 — Foundation hygiene (done as part of this session)
- [x] Local dev runs green (`75 passed`, ruff clean on new modules)
- [x] Dashboard + broker live locally on `:8001` (marketplace view)
- [x] V2 schema (sellers, watch_rules, watch_hits, listing status)
- [x] Live market baseline (P3A)

## M1 — Safe Refactors: DRY + SOLID (priority: lowest risk, zero behavior change)

### M1.1  Extract shared `scrapers/parsing.py`
- [x] Move `_extract_price`, `_extract_location`, `_INDIAN_CITIES`, `_strip_html`, `_PRICE_PATTERNS`
      into one module; Reddit + TechEnclave + scorer import from it. Delete the duplicate copies.
- [x] Verify: `pytest -q` green (75 passed); price/location/strip defined once.

### M1.2  Shared deal-signal renderers
- [x] Centralized verdict-badge data (`VERDICT_BADGES`) + plain `score_blocks()` in `present.py`; telegram + dashboard both consume. Killed dup glyph/badge logic.
- [x] Verify: no import cycle, all 75 tests pass, ruff clean.

### M1.3  Split `db/engine.py` into focused repos
- [x] `engine.py` = engine/factory only (re-exports for back-compat) · `repo_listings.py` (upsert/search/recent) · `repo_prices.py` (record/history/summary, +batch `record_prices`).
- [x] Verify: all 75 tests pass, ruff clean, dashboard imports still work.

### M1.4  `HttpFetcher` abstraction (DIP)
- [x] `scrapers/http.py`: timeout, `max_concurrent` semaphore, per-host rate limit, retry w/ backoff, proper SSL (Netskope) context.
- [x] TechEnclave rewritten onto it (deadline + retry/backoff — fixes the hang; part of M2.1).
- [x] Verify: 3 new pytest-httpx tests; TE no longer hangs; 78 tests pass; ruff clean.

### M1.5  Registry-driven `build_scrapers` (O)
- [x] `SOURCES = {name: factory}` registry; `build_scrapers` iterates it (no `if` chain). Unknown sources ignored + logged. run_scrapers tracks healthy/failed per cycle.
- [x] Verify: 78 tests pass, ruff clean.

## M1 — SAFE REFACTOR PHASE COMPLETE ✅

## M2 — Resilience (behavior-affecting)

### M2.1  Global scrape deadline + circuit breaker
- [x] TechEnclave global deadline + retry/backoff **done** (with M1.4, fixes the hang).
- [x] Per-source `CircuitBreaker` (N-fail → open for cooldown, fail-fast, concurrency-capped) + 4 tests.

### M2.2  Config extraction (12-Factor III)
- [x] Move `REQUEST_DELAY`, Netskope CA path, AI model, reddit limit into `config.py` (scraper constructor injection).
- [x] `.env.example` documents all knobs.

### M2.3  Single shared engine (12-Factor IV)
- [x] `get_engine()` caches one engine per resolved path; whole process shares a single connection pool (no "database is locked").
- [x] Verify: same handle on repeated calls; 78 tests pass; ruff clean.

### M2.4  Batch price writes + real FK
- [x] `record_prices()` batch insert (one transaction); CLI `deals` uses it.
- [x] `listings.seller_id -> sellers.id` FK on the model (applies to fresh DBs); migration stays non-destructive (SQLite can't ALTER-ADD FK — documented).
- [x] Verify: fresh DB has FK; 50-row batch inserts in one commit; 78 tests pass.

### M2.5  Graceful shutdown (Disposability)
- [x] watch mode runs on asyncio w/ SIGINT/SIGTERM handlers → cancel cycle, dispose engine pool, clean exit (was bare time.sleep loop).
- [x] Verify: SIGTERM self-test exits cleanly; 78 tests pass.

## M2 — RESILIENCE PHASE COMPLETE ✅

## M3 — Observability & Testing
- [x] Per-cycle run telemetry (`run_id, source, scraped, new, scored, failed, duration_ms, circuit`) via new `run_logs` table + `repo_meta`.
- [x] `/health` reports last-run summary.
- [x] Tests: HttpFetcher + CircuitBreaker (scrapers), `IngestionService`, dashboard routes (TestClient). 95 tests pass.

## M3 — COMPLETE ✅

## M4 — Hardware Catalog Scale-Up (from `hardware-scale-up.md`)
- [x] Catalog schema tables (`products`, `product_aliases`, `product_specs`, `msrp_history`, `city_tiers`)
- [x] Bundled curated/known-spec seed loaded via `CatalogService` (idempotent; 50 products, 167 aliases)
- [x] Normalizer reads aliases from DB (merged on top of JSON) via `engine` param
- [x] Trading-post coupon/UPI spam exclusion (negative-list; 5 tests)
- [ ] Missing aliases self-learn from AI-normalize results (guarded)

## M4 — HARDWARE CATALOG BASE COMPLETE ✅ (AI self-learn tracked as follow-up)

## M5 — AI Risk Model Correctness (from `hardware-scale-up.md`)
- [ ] Fix SCAM_RISK over-fire (confidence-gated suspicious_price, threshold 0.65→0.5 for critical)
- [ ] Layered `risk.py` aggregator (rule-first, AI only on ambiguous/high-value)
- [ ] AI cache by fingerprint (no re-billing); `max_ai_calls_per_run` guardrail

## M6 — Delivery polish (from v2)
- [ ] Coupon-deal filter tightened so real hardware cards surface
- [ ] Marketplace/dashboard wireframes finalized on real scored data
- [ ] Bot auto-push loop wired to `IngestionService` fresh events

---

## Working contract for refactors
1. **One logical change per commit** (personal rule).
2. **Green before done:** `env -u VIRTUAL_ENV -u PYTHONPATH uv run pytest -q` + ruff clean under the same prefix.
3. **No behavior change in M1** — pure organization. Behavior only changes in M2+.
4. **Cross-project edits** surfaced before made.
5. Update `docs/knowledge/pers-knowledge.md` + this board as milestones complete.