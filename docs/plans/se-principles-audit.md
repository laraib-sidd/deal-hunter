# Deal Hunter — Software-Engineering Principles Audit & Implementation Steps

**Status:** DRAFT for approval (plan-first; no code changed)
**Author:** (Laraib)
**Repo:** `~/pers/deal-hunter`

This audit evaluates the current codebase against standard software-engineering principles —
**SOLID, DRY, 12-Factor, resilience/reliability, fail-fast, separation of concerns, and
observability** — identifies which are violated (with concrete evidence from the code), and
gives ordered implementation steps to fix each. It pairs with
`docs/plans/hardware-scale-up.md` (catalog/data) — this one is about **code quality &
reliability**, not features.

---

## 0. How the audit was done
I read every module in `src/deal_hunter` during this session: `db/{models,engine,ingest,migrate,repo_dash}.py`,
`analysis/{normalizer,scorer,red_flags,ai_normalizer,ai_scorer,groq_client,pricing,baseline,schemas}.py`,
`scrapers/{base,reddit,techenclave,runner}.py`, `notifications/telegram.py`, `config.py`, `cli.py`,
`serve.py`, `dashboard/app.py`, `dashboard/present.py`, `bot/__init__.py`. The findings below are
cited to specific code, not generic advice.

---

## 1. Principle-by-principle audit

### 1.1 SOLID

**Single Responsibility (S) — VIOLATED (multiple places)**
- `db/engine.py` mixes engine creation, upsert, search, price-record, price-summary in one file
  (~136 lines). `upsert_listings`, `record_price`, `get_price_history` all live there.
- `scrapers/reddit.py` bundles regex rules, extraction, *and* the scraper class in one module.
- `dashboard/app.py` defines routes AND presentation helpers AND template-global registration
  in one file (growing toward ~200 lines).

**Open/Closed (O) — MOSTLY OK, one gap**
- Adding a scraper = new file subclassing `BaseScraper` — good (open for extension). Gap:
  `runner.build_scrapers()` hardcodes the list (`if "techenclave"... if "reddit"...`); adding a
  source requires editing this function (not closed for modification).

**Liskov (L) — OK**
- All scrapers honor the `BaseScraper` contract (`scrape(keywords, max_pages) -> list[Listing]`).

**Interface Segregation (I) — VIOLATED**
- `BaseScraper.scrape` takes `keywords, max_pages` that many sources ignore or use differently
  (Reddit uses subreddits, TechEnclave uses categories). A "fast source" vs "heavy source"
  distinction (from the v2 plan) needs a smaller, focused interface.

**Dependency Inversion (D) — PARTIALLY**
- Scrapers depend on concrete `httpx.AsyncClient` and `praw.Reddit` rather than an abstraction
  (a `HttpFetcher` interface). `IngestionService` correctly depends on an injected `engine`
  (good). `HardwareNormalizer` loads from a concrete JSON path.

### 1.2 DRY (Don't Repeat Yourself) — VIOLATED (high signal)
- **Price extraction is copy-pasted 3×**: `_PRICE_PATTERNS` + `_extract_price()` exist in
  `scrapers/reddit.py`, `scrapers/techenclave.py`, AND `analysis/scorer.py`. Three separate
  implementations of the same regex.
- **Location extraction is duplicated 2×**: `_extract_location()` in both `reddit.py` and
  `techenclave.py`, with identical `_INDIAN_CITIES` sets.
- **Indian city list duplicated 2×** (reddit + techenclave).
- **HTML-strip duplicated 2×** (`re.sub(r"<[^>]+>", ...)`) in techenclave.
- **Score-bar + verdict-badge rendering** exists in BOTH `notifications/telegram.py`
  (`_score_bar`, `_verdict_badge`) AND `dashboard/present.py` (`score_bar`, `verdict_ui`) — two
  diverging implementations of the same deal-signal visual.

### 1.3 12-Factor

**Config (III) — VIOLATED**
- `config.py` correctly uses `pydantic-settings` + env prefix `DEAL_HUNTER_` (good), BUT:
  - Several knobs are hardcoded in code: `REQUEST_DELAY = 1.5` (techenclave), `DEFAULT_LIMIT = 200`
    (reddit), `max_concurrent_requests` is in config but scrapers don't use it.
  - The Netskope CA path is hardcoded in two scrapers as `"/private/etc/netskope/..."` instead
    of a config value.
  - `ai_model`/`ai_provider` in config but `score_with_ai`/`ai_normalize` hardcode
    `meta-llama/llama-4-scout...` as default args.

**Backing services (IV) — VIOLATED**
- Every module calls `get_engine()` which opens a NEW engine per call (db/engine.py:15). There's
  no single shared engine/session dependency-injected across the app. `dashboard/app.py` works
  around this with a module-global `_engine` singleton, but `cli.py`, `bot/`, scrapers each
  create their own.

**Concurrency (VIII) — VIOLATED**
- Scrapers create a new `httpx.AsyncClient` per request (techenclave: one per `scrape()` call is
  fine, but reddit runs PRAW sync in an executor and has NO concurrency limit / rate limiter for
  subreddits). `max_concurrent_requests` config exists but is unused. No shared connection pool.

**Disposability (IX) — VIOLATED**
- No graceful shutdown handling. If the bot (`run_bot`) or `watch` loop is killed mid-write, no
  cleanup. `run_bot` has `try/finally` for the app but no signal handling.

**Dev/prod parity (X) — PARTIAL**
- Same code, but no `.env` template for all new keys; `refresh-catalog`/FX keys undocumented.

**Logs (XI) — PARTIAL**
- Good `logging.getLogger(__name__)` usage throughout (follows AGENTS.md). BUT no structured
  logging, no request-id/correlation, and no per-source run telemetry (how many scraped/scored/
  failed per cycle) beyond a few `logger.info` lines.

**Admin/process (XII) — VIOLATED**
- No `/health` deep check (dashboard has a shallow one), no metrics endpoint, no run-id.

### 1.4 Resilience & Reliability

**Fail-fast — VIOLATED**
- `runner.run_scrapers` uses `asyncio.gather(..., return_exceptions=True)` and silently `continue`s
  on scraper failure. Good for isolation but there's no health reporting — a dead source looks
  identical to a healthy one (this is why the TechEnclave hang went unnoticed).
- The TechEnclave hang (from earlier this session) is exactly this: `httpx.AsyncClient(timeout=30)`
  has a timeout, but the *loop* over categories × pages has no global deadline and no
  per-request backoff that stops runaway pagination.

**Retry/backoff — PARTIAL**
- `groq_client.py` has proper 429 retry+backoff (good model to copy). Scrapers have none for
  transient HTTP errors.

**Timeouts — VIOLATED**
- Scrapers rely on default/loose timeouts. Reddit's PRAW has none. No circuit breaker.

**Idempotency — OK (by design)**
- `upsert_listings`/`IngestionService` dedup by `(source, source_id)`; `compute_fingerprint` is
  deterministic. Good — rescraping is safe.

**Data integrity — VIOLATED**
- `record_price` does a per-row `session.add` + `commit` in a loop (db/engine.py:89) — slow and
  not atomic at scale. Should batch in one transaction.
- No FK constraint between `listings.seller_id` and `sellers.id` (it's an int column, not a real
  FK).

### 1.5 Testability

**VIOLATED (partially)**
- 75 tests pass but they test the analysis layer (pure functions). No tests for: scrapers
  (network — no mocking/cassettes), `IngestionService`, migration, dashboard routes, bot
  handlers. The scrapers are not injectable (hardwired `httpx`/`praw`).
- `pytest-recording` and `pytest-httpx` are in dev deps but unused.

---

## 2. Implementation Steps (ordered, each with verify gate)

> Phase A = no-behavior-change refactors (safe, do first). Phase B = behavior-affecting resilience.
> Phase C = testing. Each is small and lands with tests.

### Phase A — DRY + SOLID refactors (pure code organization)

**A1. Extract a shared `scrapers/parsing.py`**
- Move `_extract_price`, `_extract_location`, `_INDIAN_CITIES`, `_strip_html`, `_PRICE_PATTERNS`
  into one module. Reddit + TechEnclave import from it. Delete the 2 duplicate copies.
- **Verify:** `pytest -q` passes; `grep -r "_INDIAN_CITIES"` shows one definition.

**A2. Extract shared deal-signal renderers**
- Create `notifications/formatting.py` (or reuse `dashboard/present.py`) as the single source for
  `score_bar` + `verdict_badge`. Have BOTH telegram and dashboard import it. Delete the telegram
  duplicate (`_score_bar`, `_verdict_badge`).
- **Verify:** telegram still sends correct formatted messages (unit-test `_format_deal_message`).

**A3. Split `db/engine.py` into focused modules**
- `db/engine.py` → engine + session factory only.
- `db/repo_listings.py` (upsert/search/recent), `db/repo_prices.py` (record/history/summary),
  `db/repo_sellers.py`, `db/repo_watch.py`. Keep `repo_dash.py` for dashboard aggregations.
- **Verify:** all callers updated; `pytest -q` green; `ruff` clean.

**A4. Add a shared `HttpFetcher` abstraction (DIP)**
- `scrapers/http.py`: wraps `httpx.AsyncClient` with configurable timeout, `max_concurrent`
  semaphore, per-host rate limit, and `Retry-After` handling (reuse the groq backoff pattern).
  Scrapers depend on this interface, not raw `httpx`.
- **Verify:** `scrape --source techenclave` completes < 60s; unit-test the retry logic with
  `pytest-httpx` (no real network).

**A5. Fix `runner.build_scrapers()` to be closed for modification**
- Make it registry-driven: a `SOURCES` dict `{name: scraper_factory}`; adding a source = one entry,
  no `if` chain.
- **Verify:** adding a stub source in a test doesn't touch `build_scrapers` body.

### Phase B — Resilience (behavior-affecting)

**B1. Global deadline + circuit breaker per scraper**
- Each `scrape()` gets a hard overall timeout (config `scrape_deadline_seconds`). After N
  consecutive failures a source is "opened" to fail-fast with a logged circuit state.
- **Verify:** a stub slow source aborts under the deadline; `logger` records `circuit:open`.

**B2. Config extraction (12-Factor III)**
- Move hardcoded knobs to config: `techenclave.request_delay`, `reddit.limit`,
  `ai.model`, `netskope_ca_path`. `config.py` stays the single source of truth.
- **Verify:** `AppConfig()` exposes all; scrapers read from config; `.env.example` updated.

**B3. Single shared engine (12-Factor IV)**
- Introduce a lightweight app-container (or `lifespan` in FastAPI + a `get_engine` singleton)
  so the whole process shares one engine. Scrapers/bot/dashboard use it via DI.
- **Verify:** dashboard + a scrape + a score in one process share one `deals.db` handle with no
  "database is locked" (this bug actually occurred earlier this session).

**B4. Batch price recording + real FK (data integrity)**
- `record_price` accepts a list and inserts in one transaction. Add FK `listings.seller_id →
  sellers.id`.
- **Verify:** a 500-row batch inserts in one commit; `pytest` green.

**B5. Graceful shutdown (Disposability)**
- Wrap `serve.py` bot loop and `watch` in signal handlers (`SIGINT`/`SIGTERM`) that flush and close
  the engine cleanly.
- **Verify:** Ctrl+C exits without "Database is locked" / partial writes.

### Phase C — Observability & testing

**C1. Per-cycle run telemetry**
- Emit a structured `run_completed` log line per scrape cycle: `{run_id, source, scraped, new,
  scored, failed, duration_ms, circuit_state}`. Optional `run_id` column on listings.
- **Verify:** one grep-able line per cycle; dashboard `/health` can read last-run summary.

**C2. Real tests for the previously-untested layers**
- `tests/test_scrapers/` using `pytest-httpx` (mock Discourse/PRAW) for both scrapers — asserts
  dedup, price/location extraction, timeout behavior.
- `tests/test_ingest.py` for `IngestionService` (new/seen/reactivated/dedup).
- `tests/test_dashboard.py` for routes (FastAPI `TestClient`).
- `tests/test_bot.py` for the query parser + handlers (fake PTB `Update`).
- **Verify:** coverage of the non-analysis layers added; all pass under `env -u ... uv run pytest -q`.

---

## 3. Priority / sequencing
- **Do A1–A4 first** — pure refactors, no behavior change, de-risks everything after.
- **Then B1–B5** — the actual resilience (hang fix, shared engine, batching).
- **Then C1–C2** — lock in the reliability with tests + observability.

Each step is small and independently verifiable; none changes user-facing behavior until Phase B.

---

## 4. Files touched (all in-repo)
`scrapers/parsing.py` (new), `scrapers/http.py` (new), `scrapers/{reddit,techenclave,runner,base}.py`,
`db/{engine,repo_listings,repo_prices,repo_sellers,repo_watch}.py`, `notifications/formatting.py` (new),
`notifications/telegram.py`, `dashboard/present.py`, `dashboard/app.py`, `config.py`, `cli.py`,
`serve.py`, `bot/__init__.py`, `tests/*` (new), `.env.example`.

## 5. Done-Definition (worker must produce ALL)
1. No duplicated price/location/score-renderer logic remains (DRY audit passes).
2. Scrapers depend on `HttpFetcher`; global deadline + circuit breaker enforced; TechEnclave
   never hangs.
3. One shared engine per process; batch price writes; real FK.
4. All config from `config.py`/env; `.env.example` complete.
5. Run telemetry emitted; `/health` reports last-run.
6. New tests for scrapers/ingest/dashboard/bot pass alongside existing 75.
7. `ruff` clean; `pytest -q` green under `env -u VIRTUAL_ENV -u PYTHONPATH`. Commit focused.
