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
- [ ] `scrapers/http.py`: timeout, `max_concurrent` semaphore, per-host rate limit, retry w/ backoff.
- [ ] Scrapers depend on it, not raw `httpx`.
- [ ] Verify: TE scrape < 60s; retry logic unit-tested w/ `pytest-httpx`.

### M1.5  Registry-driven `build_scrapers` (O)
- [ ] `SOURCES = {name: factory}`; adding a source = one entry, no `if` chain.

## M2 — Resilience (behavior-affecting)

### M2.1  Global scrape deadline + circuit breaker
- [ ] Hard overall timeout per `scrape()` (config `scrape_deadline_seconds`); N-fail → fail-fast w/ `circuit:open` log.
- [ ] Fixes the TechEnclave hang (loose pagination loop has no global deadline).

### M2.2  Config extraction (12-Factor III)
- [ ] Move `REQUEST_DELAY`, Netskope CA path, AI model, reddit limit into `config.py`.
- [ ] `.env.example` complete.

### M2.3  Single shared engine (12-Factor IV)
- [ ] One engine per process (lifespan/DI); dashboard+scrape+score share one `deals.db` handle.
- [ ] Verify: no "database is locked" (occurred earlier this session).

### M2.4  Batch price writes + real FK
- [ ] `record_price` takes a list, one transaction; FK `listings.seller_id -> sellers.id`.

### M2.5  Graceful shutdown (Disposability)
- [ ] Signal handlers (`SIGINT`/`SIGTERM`) flush + close engine cleanly in bot + watch.

## M3 — Observability & Testing
- [ ] Per-cycle run telemetry (`run_id, source, scraped, new, scored, failed, duration_ms, circuit`).
- [ ] `/health` reports last-run.
- [ ] Tests: scrapers (pytest-httpx), `IngestionService`, dashboard routes (TestClient), bot handlers.

## M4 — Hardware Catalog Scale-Up (from `hardware-scale-up.md`)
- [ ] Catalog schema tables (`products`, `product_aliases`, `product_specs`, `msrp_history`, `city_tiers`)
- [ ] Bundled curated/known-spec seed (~300-400 SKU GPU+CPU) loaded via `CatalogService`
- [ ] Missing aliases self-learn from AI-normalize results (guarded)
- [ ] Normalizer reads aliases from DB (not JSON), token-normalized match stage
- [ ] Per-category deal thresholds + `category_advice` (from `second-hand-buys.md`)
- [ ] Trading-post coupon/UPI spam exclusion (negative-list)

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