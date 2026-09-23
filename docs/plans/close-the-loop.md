# Close the loop — scrape, ingest, signals, dashboard

**Status:** ready for `/go` (no code in this pass)
**Author:** (Laraib)
**Repo:** `~/pers/deal-hunter`
**Supersedes for execution:** the unwired parts of `docs/plans/deal-hunter-v2.md` and the “done” boxes in `docs/plans/milestones.md` that describe tables the cron job never writes. Those files stay as history. This file is the bus.

## Why

Production cron is `deal-hunter scrape && deal-hunter deals --ai --min-score 5 --notify` (`deploy/contabo/docker-compose.yml`). That path inserts new rows and forgets the rest, scores in memory, then Telegrams the same recent window every two hours.

What already exists and must be used, not rewritten:

- `IngestionService.ingest_batch` (`db/ingest.py`) upserts sellers, bumps `times_seen`, updates price, reactivates `dead`. Tested. Never called from `cli.py`.
- `upsert_listings` (`db/repo_listings.py`) is insert-or-skip. A price drop on a known `(source, source_id)` is discarded.
- `Listing.deal_score` / `deal_verdict` are what `repo_dash.active_deals` and the bot badge read. Nothing assigns them.
- `analyze_deal_async(..., engine=)` blends fair value toward the live median (`analysis/scorer.py`). CLI never passes `engine`.
- `run_scrapers(..., engine=)` writes `run_logs` (`scrapers/runner.py`). `scrape` and `watch` omit `engine`, so `/health` has no last run.
- `compute_fingerprint` hashes `title|price|location`. A price edit is a new fingerprint even though ingest keys on `(source, source_id)`.
- TechEnclave fetches every topic body (`/t/{id}.json`) after listing four categories × N pages, then sleeps again on top of `HttpFetcher`’s per-host delay. `HARDWARE_TAGS` is unused. Category 18 (looking-to-buy) is ingested as if it were a sale.
- Reddit calls `subreddit.new(limit=pages * reddit_limit)` from the top every run. `watch --ai` is accepted and ignored (`_watch_loop` calls sync `analyze_deal`).
- `--notify` sends a summary plus up to 10 individual alerts for whatever scored this run (`cli._send_deal_alerts`). No `alerted_at`. The next cron repeats them.
- Dashboard deals cards and `price_delta` exist (`dashboard/app.py`, `present.py`). The product page’s “sparkline” is a comment above a table (`product.html`). The top bar says LIVE with no last-run check (`base.html`). Filters on `/deals` are client-side `display:none`.

## Locked decisions

Do not revisit these.

1. **One cycle.** `scrape → IngestionService → score only the delta → alert once → dashboard reads the columns.` Cron and `watch` both call that cycle. `deals` becomes a read of persisted scores, plus `deals --rescore` as an explicit backfill.
2. **Keep v2 delivery and stack.** Telegram DM bot stays. Auto-push stays. Dashboard stays server-rendered FastAPI + Jinja. SQLite + SQLModel. Contabo container. Secrets in `.env` only. No React.
3. **No new sources.** Reddit and TechEnclave only. OLX / Facebook / retail baseline / Playwright stay out. v2 already marked OLX and Facebook blocked.
4. **Deterministic verdict stays the signal.** `score_with_ai` and `aggregate_risk` stay off the hot path. Groq is only the existing unknown-product normalizer inside `analyze_deal_async` when the local catalog misses. Pass `engine` so the live median actually moves fair value.
5. **Identity of an offer is `(source, source_id)`.** That pair gets a real unique index. Fingerprint drops price (`title|location` only) and is not unique. Two posts for the same card stay two offers. `canonical_name` is how the product page groups them.
6. **Incremental scrape must not bury old rows.** A cycle that only reads the front of a forum does not mark “not in this batch” as dead. Stale is time-based (below).
7. **Alert once.** Telegram fires for new or reactivated offers that score at or above the threshold with verdict `BUY` or `NEGOTIATE`, and again only when the asking price drops by ≥ 8%. Cap 5 listing messages per run. Send the summary only when that count is non-zero. Category `wtb` and `other` never alert.
8. **Watch rules use the same delta.** Match `WatchRule` against fresh and price-drop rows. Write `WatchHit`. Alert when `enabled` and `alert_on_newest` and `alerted_at` is null. Bot query applies the locations it already parses.
9. **Dashboard look follows `docs/design/deal-hunter-ui.md`.** Signal color only (buy / negotiate / pass / scam). No new chart library. No HTMX (specified in v2, never installed; GET forms are enough). Mobbin was not available (paid plan); do not invent a second visual language.
10. **No new HTTP retry library.** httpx transport `retries` only covers connect failures (`https://www.python-httpx.org/advanced/transports`). Keep application-level retry in `HttpFetcher`.

## Target cycle

```
run_scrapers(engine=…)          # cursors in, run_logs out
  → TechEnclave / Reddit        # stop at known ids; detail only when needed
  → IngestionService.ingest_batch
        new | seen | reactivated | price_drops
        sellers, times_seen, last_confirmed_at
        PriceSnapshot only when price is new or changed
  → score_delta(fresh + price_drops, engine=…)
        writes deal_score, deal_verdict, deal_reason, canonical_name, red_flags_json
  → match watches, send Telegram, set alerted_at
  → /deals and / read those columns
```

`cli.py` is the only orchestrator. It is wired last, after the pieces exist.

## Slice A — Scraper core

**Files:** `src/deal_hunter/scrapers/http.py`, `base.py`, `runner.py`, `parsing.py`, `src/deal_hunter/db/repo_meta.py`, `tests/test_scrapers/test_http_fetcher.py`, `tests/test_scrapers/test_circuit_breaker.py`

**Behavior:**

- `HttpFetcher` sets `httpx.Limits(max_connections=4, max_keepalive_connections=2)` and `httpx.Timeout(15.0, connect=5.0)`. One Discourse host does not get the library default of 100 connections (`https://www.python-httpx.org/advanced/resource-limits`, `https://www.python-httpx.org/advanced/timeouts`).
- Per-host throttle updates `_last_request` under the same lock as the wait, so two coroutines cannot both see “wait is zero”.
- `Retry-After` is honored only when it parses as delta-seconds. An HTTP-date falls back to exponential backoff, capped at 30s. 429/5xx retry stays in `HttpFetcher`. Connect retries may use `AsyncHTTPTransport(retries=1)` in addition, not instead.
- `get()` grows a small result the circuit breaker can see: success, not-found, or exhausted. Scrapers still skip a single failed topic. A source that exhausts retries on its list call counts as a failure for `CircuitBreaker`.
- `BaseScraper.scrape` gains `known_ids: set[str] | None = None`. Default `None` means today’s full window, so callers keep working before slices B and C.
- `parsing.py` gains `classify_intent(title, body, category_hint) -> "sell" | "wtb" | "other"`. Spam and coupon patterns move here (the copies in `reddit.py` are removed in slice C). WTB phrases and the TechEnclave looking-to-buy hint return `wtb`. Coupon / UPI / travel return `other`.
- `repo_meta.py` stores a cursor per `(source, bucket)` — bucket is a category id or subreddit name. `run_scrapers` loads those ids when `engine` is passed, passes them as `known_ids`, and after a successful source advances the cursor to the newest id that source reported. Failed sources do not move the cursor.
- `run_scrapers` writes `run_logs` whenever `engine` is passed. Slice G is what starts passing it.

**Test:** `uv run pytest -q tests/test_scrapers/test_http_fetcher.py tests/test_scrapers/test_circuit_breaker.py`

## Slice B — TechEnclave

**Files:** `src/deal_hunter/scrapers/techenclave.py`, `tests/test_scrapers/test_techenclave.py`
**Blocked by:** A (`known_ids`, `classify_intent`, fetcher result).

**Behavior:**

- Category JSON is the discovery step. Discourse topic ids are monotonic. Stop paging a category when a topic id is in `known_ids` or older than the cursor. Do not call `/t/{id}.json` for those.
- Detail-fetch only ids that are new, or whose `bumped_at` / `last_posted_at` is newer than the stored listing. Cap detail fetches per cycle at 40 so the deadline is a backstop, not the design.
- One delay only: `host_min_interval`. Remove the extra `asyncio.sleep` after each topic.
- Map categories: 64, 61, 19 are sales. 18 is `category="wtb"` via `classify_intent` and is stored but never treated as a deal later. Coupons and travel become `category="other"`.
- Keep seller as the first post’s username (`seller_name` is already set in `_fetch_topic_detail`).
- Search mode (`--keywords`) uses `search.json` with a `page` param up to `max_pages`, still deduped by topic id.
- Deadline uses `time.monotonic()`, not `get_event_loop().time()`.

**Test:** `uv run pytest -q tests/test_scrapers/test_techenclave.py`

## Slice C — Reddit

**Files:** `src/deal_hunter/scrapers/reddit.py`, `tests/test_scrapers/test_reddit.py`, `tests/test_scrapers/test_spam_filter.py`
**Blocked by:** A.

**Behavior:**

- Keep PRAW in an executor. `subreddit.new()` is newest-first; break the generator when `submission.id` is in `known_ids` for that sub. That stops the next HTTP page. Missing credentials still skip the source with a warning, and the runner records the skip rather than a crash.
- Hardware subs keep sale-and-hardware. Deal subs (`IndiaDealsExchange`, `dealsforindia`) use the same hardware requirement plus `classify_intent`. A coupon thread with no hardware match is `other` and is not appended. This is the noise cut. Do not drop the subs entirely.
- `max_pages * reddit_limit` remains the upper bound for a cold start (empty cursor). A warm cursor should stop in far fewer items.
- Spam regex lives in `parsing.py` after slice A. Reddit tests import that.

**Test:** `uv run pytest -q tests/test_scrapers/test_reddit.py tests/test_scrapers/test_spam_filter.py`

## Slice D — Ingest is the only writer

**Files:** `src/deal_hunter/db/ingest.py`, `models.py`, `migrate.py`, `tests/test_db/test_ingest.py`, `tests/test_db/test_engine.py`
**Does not edit** `repo_listings.py` (slice G stops calling it).

**Behavior:**

- `IngestionService.ingest_batch` stays the writer. On price change, append one `PriceSnapshot` through the existing `record_prices`. Do not snapshot when the price is unchanged.
- Return price-drop listings on `IngestionResult` (new field `price_drops: list[tuple[Listing, old_price, new_price]]`). `fresh` stays `new + reactivated`.
- `persist_scores(engine, rows: list[tuple[int, DealAnalysis]])` writes `deal_score`, `deal_verdict`, `deal_reason`, `canonical_name`, `red_flags_json` on those listing ids. One transaction.
- `mark_alerted(engine, listing_ids: list[int])` sets new nullable `listings.alerted_at`.
- `compute_fingerprint(title, location)` drops price. Existing rows are not rewritten.
- Unique index `uq_listing_source_item` on `(source, source_id)`. `SQLModel.metadata.create_all` does not alter an existing SQLite table (`db/migrate.py` already says this). Migration steps, in order: delete duplicate `(source, source_id)` keeping the lowest id, then `CREATE UNIQUE INDEX IF NOT EXISTS`. New databases get the constraint from the model `__table_args__`.
- Stale sweep, separate method `mark_stale(engine, now)`: `active` and `posted_at` older than 21 days → `stale`. Do not flip a row to `dead` because this cycle’s cursor window did not include it. `dead` remains only what ingest already does when a previously dead row comes back (reactivate) or a later explicit rule. No absence-based death.
- Seller `is_suspect` is not guessed here. Flag counts stay for a later epic.

**Test:** `uv run pytest -q tests/test_db/test_ingest.py tests/test_db/test_engine.py`

## Slice E — Signals and alerts

**Files:** `src/deal_hunter/alerts/__init__.py`, `alerts/pipeline.py`, `alerts/match.py`, `src/deal_hunter/bot/__init__.py`, `tests/test_alerts/test_pipeline.py`, `tests/test_alerts/test_match.py`, `tests/test_analysis/test_telegram.py`
**Blocked by:** D (`persist_scores`, `mark_alerted`, `price_drops`).

**Behavior:**

- `score_delta(engine, listings, *, ai_api_key: str)` calls `analyze_deal_async` with `engine` so `_build_analysis` blends the live median. Skip rows with no price, and rows whose `category` is `wtb` or `other`. Then `persist_scores`.
- `decide_alerts(listings, analyses, *, min_score: int) -> list` keeps verdict in `{BUY, NEGOTIATE}`, score `>= min_score`, and (`alerted_at` is null or this row is in `price_drops` with a drop ≥ 8%). Cap 5.
- `match_watches(engine, listings, analyses)` loads enabled `WatchRule`s. A hit requires every set constraint: query tokens in title or canonical name, `max_price`, location (rule locations empty means any), `min_score`. Insert `WatchHit` once per `(rule_id, listing_id)`.
- `dispatch(engine, config, alerts)` sends those listing messages, then one summary only if the list is non-empty, then `mark_alerted`.
- `bot` `on_message` filters by the locations `parse_query` already returns.

**Test:** `uv run pytest -q tests/test_alerts tests/test_analysis/test_telegram.py`

## Slice F — Dashboard reads the truth, and looks like the spec

**Files:** `src/deal_hunter/dashboard/app.py`, `present.py`, `templates/base.html`, `index.html`, `deals.html`, `marketplace.html`, `product.html`, `watch.html`, `tests/test_dashboard/test_routes.py`
**No file overlap** with A–E. It will look empty until G has run against a real DB. Build the states anyway.

**Behavior, from `docs/design/deal-hunter-ui.md`:**

- `/deals` card is the shortlist: verdict chip, canonical name or title, mono asking price, delta badge (`N% below` / `above`), score bar, source, location, relative time, one Open link. Server-side GET filters for source, verdict, and a search string. Delete the client-side `display:none` filters.
- Empty copy has two lines, picked in the view: no priced listings yet, versus listings exist but none are scored at or above 6. The second line tells the truth (“scoring has not been written onto these rows”), not “run deals” as if the column should already be there.
- `/` stat row keeps the four cards from the spec (new in 24h, active, deals ≥ 6, watches). The “▲ buy signals” line renders only when `active_deals > 0`. Otherwise the delta line is muted, not a green arrow on zero.
- LIVE pill uses `last_run_summary`: LIVE if the newest run is under 3 hours, STALE if older, OFF if there is no row. Color is the existing buy / warn tokens, not a new palette.
- Remove the brand-mark `linear-gradient` in `base.html`. The spec’s rule is luminance steps, and color means deal quality.
- `/product/{canonical}` draws an inline SVG polyline of `price_history` (no chart library) with the median as a horizontal line, plus the existing p25/p75/median stats. Offers table stays.
- `/marketplace` stays the browse table. Default sort is newest `last_confirmed_at`. Verdict filter hits persisted `deal_verdict`.
- `/watch` lists rules and recent hits with the listing title, not only an id.

**Test:** `uv run pytest -q tests/test_dashboard/test_routes.py`

## Slice G — Wire cron and watch to the cycle

**Files:** `src/deal_hunter/cli.py`, `deploy/contabo/docker-compose.yml`, `deploy/contabo/scripts/cron-run.sh`, `tests/test_cli/test_cycle.py`
**Blocked by:** A, B, C, D, E.

**Behavior:**

- New command `deal-hunter run` (and the body of `watch`) does: `run_scrapers(..., engine=engine)` → `ingest_batch` → `mark_stale` → `score_delta` on `fresh + price_drops` → `match_watches` → `dispatch` when `--notify`. `watch --ai` passes the Groq key into `score_delta`. It does not call `analyze_deal` without a key.
- `scrape` alone still ingests via `IngestionService` and passes `engine`, and does not alert.
- `deals` prints persisted rows with `deal_score >= min_score`. It does not rescore and does not snapshot unchanged prices. `deals --rescore` runs `score_delta` on the recent priced window once, for backfill, and still obeys alert-once.
- Compose and `cron-run.sh` call `deal-hunter run --ai --min-score 6 --notify` as one process. Remove the `scrape && deals --notify` pair that re-alerts the window.
- One test: fixture listings from both sources → ingest → score persist → second ingest of the same ids with the same price sends nothing → same id with an 8% lower price is eligible again. Dashboard test client is out of this slice; slice F covers routes.

**Test:** `uv run pytest -q tests/test_cli/test_cycle.py`

## Gotchas

- Deduplicate `(source, source_id)` before the unique index. A failed `CREATE UNIQUE INDEX` means the migration met real duplicates. Do not catch and continue.
- Changing the fingerprint formula does not merge old rows. Do not run a rewrite.
- Detail-fetch cap of 40 can leave a busy TechEnclave hour partially unscored until the next cron. Cursor advances only for ids actually processed, so the next run continues. Do not advance past an unfetched id.
- PRAW stays synchronous inside the executor. Do not call it on the event loop.
- Netskope CA path stays a config knob. The VPS has no such file; `_tls_context` already falls back to default verify.
- `alerted_at` is per listing, not per chat. This deploy has one chat. Do not build a delivery log.
- Playwright extras in `pyproject.toml` are unused. Do not import them.
- Dashboard has no auth. This epic does not add it. Do not publish port 8001 to the public interface as part of the visual work.
- CI in `.github/workflows/deploy.yml` pushes `:latest` before pytest. Out of scope. Do not “fix” it inside slice G.

## Done

- `uv run pytest -q` is green, and `uv run ruff check src/` is clean.
- A second `run` on an unchanged fixture sends zero Telegram messages.
- A new fixture offer with a score ≥ 6 and verdict BUY has `deal_score` set, and `GET /deals` shows that score and a below/above delta.
- TechEnclave test proves a known topic id does not trigger `/t/{id}.json`.
- Reddit test proves the generator stops at a known id.
- `/health` last-run is populated when `run` is given an engine.
- `docs/knowledge` is not edited by the implementer. The parent harvests durable notes after `/go`.

## Waves

File lists are disjoint. Edges are only where a later slice calls a signature the earlier slice owns.

| Wave | Beads | Why together |
|---|---|---|
| 1 | A scraper core, D ingest, F dashboard | No shared files. F renders columns that already exist. |
| 2 | B TechEnclave, C Reddit, E alerts | B and C need A’s `known_ids`. E needs D’s persist/alert columns. The three do not share files. |
| 3 | G wire CLI and cron | Calls A–E. One file owner for `cli.py`. |

## Out of scope

OLX, Facebook, retail price baseline, HTMX, `score_with_ai` as the verdict, catalog self-learn, dashboard auth, CI job order, seller trust scoring beyond the columns that already exist.
