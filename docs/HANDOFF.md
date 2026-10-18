# HANDOFF — ebay-hunter (generated 2026-10-01, refreshed 2026-10-06)

**Read this first, then run the verification block in §1 before changing anything.**

This file exists so a fresh session can resume without re-deriving anything.
The 2026-10-06 refresh updated the baseline to `911`, closed §4.5's decision
queue (all six answers now in the code), rewrote "Still not done" against what
actually remains, and recorded the provenance-persistence work. Everything
below §4.5 that predates that refresh describes commits that have since
landed — trust the commit chain, not any "nothing committed" claim.
A previous handoff lives at `%TEMP%\opencode\handoff-ebay-hunter-2026-09-29.md`
(commit `cf6e094` message holds the original assumptions/deferred findings —
do not duplicate them here).

---

## 0. What this project is

A UK eBay reselling-research tool. Five features, one contract:

| Feature            | Backend entry                                                         | Frontend route |
| ------------------ | --------------------------------------------------------------------- | -------------- |
| Analyze / URL-hunt | `backend/analysis_pipeline.py` → `backend/api/analyze.py`             | `/analyze`     |
| Deep Search        | `backend/deep_search.py` → `backend/api/deep_search.py`               | `/deep-search` |
| Bulk               | `backend/deep_search.py` (`deep_search_fast`) → `backend/api/bulk.py` | `/bulk`        |
| Category Hunter    | `backend/hunter/*` → `backend/api/hunter.py`                          | `/hunter`      |
| History / exports  | `backend/api/history.py`, `backend/export/*`                          | `/history`     |

The product promise: **every number on screen is traceable to a source, or it
is explicitly labelled as not verified.** A fabricated price costs real money.

---

## 1. Verification (run this before and after every change)

```powershell
# Backend tests — baseline is 1163 passed. Live tests carry the `live` marker
# and are deselected by pytest.ini; run them on demand with `pytest -m live`.
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/ -q

# Import smoke (catches circular imports / missing symbols fast)
python -c "import sys; sys.path.insert(0,'backend'); import main, pipeline, analysis_pipeline, deep_search, api.analyze, api.bulk, api.deep_search, api.hunter, api.demand_monitor, export.format, export.csv_export, hunter.supplier_lookup, hunter.demand_monitor, engine.match; print('OK')"

# Frontend typecheck — baseline exit 0. Run from the REPO ROOT:
npm run typecheck       # == npm --prefix frontend run typecheck
# (`npx tsc` from the root fails: typescript is not installed there.)
```

**Live tests (opt-in, spend real API quota against 5,000/day):**

```powershell
$env:EBAY_LIVE='1'
python -m pytest tests/test_live_smoke.py -m live -q
```

**Re-capturing the real API fixtures** (only when a vendor changes shape):

```powershell
$env:SERPAPI_KEY = (Select-String -Path .env -Pattern "^SERPAPI_KEY=").Line -replace "^SERPAPI_KEY=",""
python tests\capture_fixtures.py
python -m pytest tests/test_real_payload_fixtures.py -q
```

**Console note:** always set `$env:PYTHONIOENCODING='utf-8'` first. Printing
badge emoji on cp1252 crashes the run.

**Never run `next build` while `next start` is running** — it clobbers `.next`.

**`npm run lint` is BROKEN and always was** — Next 16 no longer accepts a
positional arg, so `next lint` errors with
`Invalid project directory provided ... frontend\lint`. Pre-existing, not a
regression. **`tsc --noEmit` is the frontend gate.**

### Current state (verified 2026-10-06)

- `911 passed, 7 skipped, 63 warnings` ✅
- `npm run typecheck` → **exit 0** ✅
- Live smoke tests against the real APIs → `7 passed` ✅
- HEAD `9a8a3bb` on `main`, pushed. Backend booting on `:8000`,
  migration in `db.database` ran clean against the existing database.
- Pushed through `6fb2aa6`. See §4.5 for what landed since `78a8852`.

### Running the app

```powershell
# Backend (from backend/)
python -m uvicorn main:app --host 127.0.0.1 --port 8000
# Frontend (from frontend/)
npx next start -p 3000
```

Start detached with `Start-Process cmd.exe` and log to
`$env:TEMP\opencode\*.log` so a hung shell does not eat the session.

---

## 2. The five constraints (source of truth: `CONSTRAINTS.md` v1.1)

Spec amendments are **C10–C14**. Code aligns TO the spec, never the reverse.

- **C10 — New-only condition gate.** `engine/condition_gate.py`. Enforced at
  query time (API filter AND URL param) in `scrapers/ebay.py`,
  `scrapers/ebay_sold.py`, `hunter/category_scan.py`. Blank/unknown condition
  **fails closed**. A silent `"New"` default was a real bug — fixed in
  `scrapers/base.py`, `ebay.py`, `category_scan.py`, `profit_calc.py`,
  `deep_search.py`, `llm/prompts.py`. Do not reintroduce it.
- **C11 — up to 4 REAL eBay stores.** `engine/stores.py`. From real
  `seller.username`; URL derived `ebay.co.uk/str/{username}` and marked
  `url_derived: true`; `sold_count` labelled
  **"observed listings (search window, cap 50)"** — it is NOT eBay's sold
  count. Wired into all 5 features + both CSV/JSON exports.
- **C12 — up to 7 suppliers, fewer is correct.** `config.MAX_SUPPLIERS = 7`.
  A row exists only if retrieved AND cleared the C14 threshold. **Never pad.**
- **C13 — four-tier provenance.** `engine/provenance.py`:
  `verified` / `estimated` (must carry `method`) / `unverified` / `ai_insight`.
  `ai_insight` is **structurally barred** from factual fields
  (`assert_not_ai_fact()` walks dicts/lists and raises). The LLM may analyse
  facts it was handed; it may never supply a name, price, URL, stock or sold
  count. `deep_search.py` unconditionally `parsed.pop()`s `ebay_top_sellers`
  and `suppliers`.
- **C14 — deterministic matching.** `engine/match.py`. Thresholds:
  `>= 0.65 verified` · `0.45–0.65 unverified` · `< 0.45` →
  **"no confirmed match"**, row dropped. `match_score` is computed, never a
  constant; LLM confidence is display-only.

### Golden rule

> **Missing/unknown renders as `unverified` (or blank), never `verified`.**
> An empty dict `{}` for a provenance block is a contract violation — stamp it
> with `unverified` + a `reason`.

---

## 3. What is DONE

| Phase               | Deliverable                                                                                                                                                                                                                    | Tests     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------- |
| **P0**              | `CONSTRAINTS.md` v1.1 — C10–C14 added                                                                                                                                                                                          | —         |
| **P1**              | `engine/condition_gate.py` + query-time enforcement in all 5 features; `PUT /api/filters` accepts `condition`, 422 for non-New                                                                                                 | 137 → 153 |
| **P2**              | `engine/provenance.py` (Fact guards, AST anti-fabrication test); LLM facts killed in `deep_search`/`pipeline`/`llm/prompts`; `engine/source_type.py`; export provenance columns. **Doc: `docs/P2-changes.md` (user-approved)** | → 245     |
| **P3**              | `engine/stores.py` (C11) wired into Analyze, URL-hunt, Deep Search full+fast, Bulk, Hunter, both exports, frontend card                                                                                                        | → 355     |
| **P4a**             | `scrapers/serpapi_discovery.py` — SerpApi primary discovery for all 7 suppliers; `suppliers.json` gained `domains[]`; broken `aliexpress`/`amazon_uk` clients fail closed                                                      | 355       |
| **P4-avail**        | `scrapers/availability.py` + 6 fields on `ScrapedProduct` (`in_stock`, `stock_raw`, `availability_url`, `shipping_cost`, `shipping_days`, `shipping_raw`) populated across 9 scrapers                                          | 355       |
| **P4b**             | **`engine/match.py`** — C14 matcher (Dice title + brand + attributes + price plausibility + pHash, three hard vetoes)                                                                                                          | → **539** |
| **P4c-wire**        | Matcher gated into **all 5 consumers** (§5) + `MAX_SUPPLIERS` cap + availability threading                                                                                                                                     | 539       |
| **API/export pass** | `api/provenance_block.py`; every return path stamps provenance; CSV/JSON carry stores + availability + match                                                                                                                   | 539       |
| **P5a**             | Frontend: `lib/provenance.ts`, `ProvenanceBadge`, `ProvenanceSelect`, `EbayStoresCard`, `types.ts` extended                                                                                                                    | tsc 0     |

### Bugs found and fixed in `engine/match.py` during review

1. `_quantities` never saw `"3 pack"` (tokenizer dropped the bare digit) → a
   3-pack eBay listing **confirmed** as a 1-pack supplier. Fixed: quantity
   detection moved to raw title via `_QTY_RAW_RE`.
2. Unguarded `float()` in the price veto → `ValueError`/`ZeroDivisionError`
   on `"£19.99"` / `"0"`. Fixed: `_price_ratio()` returns `None`.
3. Model split as digit-run + alpha (`WH1000` + `XM4`) vetoed against
   `WH1000XM4`. Fixed: alnum heads now merge too.
4. **A totally unrelated title scored 0.55 and CLEARED the 0.45 floor** —
   brand/attributes/price all score neutral 1.0 when there is nothing to
   contradict them, so a disjoint pair collected points on the _absence_ of
   evidence. Fixed: veto 0 "no shared title tokens" caps at 0.30. Applied
   **last** so a more specific reason (model/brand/price) still wins.
5. Components are rounded to 4dp **before** weighting, so the sum was e.g.
   `0.44999` while the displayed score was `0.45` → a row could show a
   passing score and still be dropped. Fixed: **round once, before tiering**
   — whatever we print is what we judge by.

All five are locked in by `tests/test_match.py` (187 tests).

### P4 integration tests — DONE

`tests/test_match_wiring.py` (**67 tests**) proves each of the five
consumers really routes through the gate. Its own docstring is the best
guide to the coverage.

---

## 4. What is NOT done (resume here)

### 4.1 ~~Two agents were rate-limited~~ — BOTH LANDED, nothing was lost

Both task results came back as errors, but each had **already written its
file**. Verified independently:

- ✅ **`tests/test_match_wiring.py` — EXISTS, 67 tests, passing.**
  Integration coverage for the C14 gate across all five consumers: gate
  actually gates; unscored ≠ pass (`match_tier == ""` default); cap of 7 and
  never padded; Hunter picks the best _match_ not the cheapest row;
  availability fields survive into the result; provenance never overclaimed.
- ✅ **Frontend match + stock display — DONE.**
  `frontend/components/ui/MatchBadge.tsx` (new), `SupplierCard.tsx`,
  `lib/types.ts`, `Badge.tsx`.

The critical rule is implemented correctly — `describeMatchTier()` returns
`null` for `""`/null/absent/unrecognised, so **an unscored row renders
nothing**. Score is shown only for `verified`, at 2dp, and only when
`Number.isFinite`. Stock prefers `in_stock`, falls back to `stock_raw`
verbatim, else `STOCK_NOT_STATED = "Stock: not stated"`; shipping prefers
`shipping_raw`, else cost/days, else `SHIPPING_UNKNOWN = "Shipping: unknown"`
— never "£0.00" or "Free".

**Lesson:** a failed task result does not prove nothing was written. Check
the filesystem before re-running an agent.

### 4.2 P4 — DONE (commits `8320a7f` + `78a8852`)

Both remaining items are closed. **Do not redo P4.**

**SerpApi discovery.**

It turned out the module had never been run: `google_shopping` results carry
**no merchant URL at all** (`link` is absent, `product_link` is always
`https://www.google.com/...`), so the domain-match never fired and `_row_for`
dropped every row for a missing `url`. Verified against the live API.

Rewritten as three stages sharing one budget of `MAX_CALLS = 10` requests:

1. **SEARCH** — one `google_shopping` call (+ a `site:` pass per missed
   supplier) identifies the supplier from `source` and reads Google's title
   and price.
2. **RESOLVE** — one `google_immersive_product` call per row we keep returns
   `product_results.stores[]`, the only place SerpApi publishes the merchant
   URL, offer price, `shipping` line and stock wording.
3. **BUILD** — coverage first (every supplier's first row, then spares),
   capped at `MAX_SUPPLIERS`.

The slug comes from the **offer's own domain**, never from where Google filed
the search result — a test locks that in (a B&Q offer surfacing under a
Toolstation search must not be labelled Toolstation).

Wired into:

- `analysis_pipeline.search_all_suppliers` — discovery runs concurrently with
  the seven scrapers, deduped by URL.
- `deep_search` — discovery is the **primary** source, LLM candidate URLs the
  **supplement**, deduped by URL before the gate.
- `_gate_suppliers` now applies the C12 cap (`config.MAX_SUPPLIERS`) _after_
  the match gate, so survivors are the strongest matches.

Live smoke (2026-10-01): 5 rows across Amazon UK / B&Q / Toolstation, real
`toolstation.com` / `diy.com` / `amazon.co.uk` URLs, `in_stock`, `shipping_raw
= "Free"` with `shipping_cost = 0.0`. Site passes time out sometimes; the
budget stops cleanly.

**Image pHash — DONE (commit `78a8852`).**

C14 says "image phash when both images exist"; `compute_match` had accepted
`ebay_image_hash`/`candidate_image_hash` from the start but **no caller ever
passed one**. Now `engine/match.py::image_hash_for(url)` downloads, hashes
and caches by URL, and all five consumers thread a reference hash through:

| Consumer                                     | Reference image comes from                                                   |
| -------------------------------------------- | ---------------------------------------------------------------------------- |
| `analysis_pipeline._score_supplier`          | `ebay_product.image_url`, hashed once in `run_analysis_pipeline`             |
| `pipeline._match_gate` / `_search_suppliers` | `product.image_url`, hashed before `asdict`                                  |
| `hunter.supplier_lookup._first_valid`        | `CategoryProduct.image_url`, per product                                     |
| `deep_search._gate_suppliers` (full + fast)  | `_reference_image_hash(sold_for_stores)` — first readable sold-listing image |
| (engine) `score_candidates`                  | reads `row["image_hash"]`, `ebay_image_hash` kwarg                           |

Two rules hold everywhere: **no reference hash → no candidate download**
(without an eBay image there is nothing to compare, so fetching is pure
cost), and an unreadable image yields `None` so the score _loses_ that
component rather than gaining a made-up one.

`requests` is imported **inside** `image_hash_for`, keeping `match.py`
importable with no network stack (so `compute_match` stays pure). Only
`RequestException`/`ValueError`/`OSError` are caught, so a test sentinel like
`_zero_network`'s `AssertionError` is never swallowed.

### 4.3 P6 — documentation

- `docs/P3-changes.md`, `docs/P4-changes.md` not written (only `P2-changes.md`
  exists). User asked for a change doc per phase — **ask before writing**;
  docs are only created on request.
- Final summary / plan close-out.

### 4.4 Deferred / known gaps (do not "discover" these again)

- `backend/api/deep_search.py` timeout path was fixed to stamp `unverified`;
  confirm it still matches `api/analyze.py` (both were touched in the pass).
- `export/format.py` does not re-cap stores to 4 — all producers already cap.
- `analysis_pipeline.py:~307` skips the free `products=` path when sold data
  is empty (intentional; extra request only).
- AliExpress/Amazon Playwright fallbacks deliberately still alive: only the
  credential-dependent _API attempts_ fail closed. Making `.search()` return
  `[]` outright would strip those rows from files not yet rewired.
- `aliexpress_api.py` left untouched (correct host, zero callers, fails closed
  with no key).

---

## 4.5 What landed after `78a8852` (do not redo these)

Commits, in order: `3f83493` handoff → `55df554` Category Hunter fixes →
`82b414f` competitor-store fix → `f0a19e5` windowed Hot Items + competitor
count → `7b61037` Hot Items UI → `8290709` demand monitor → `6f71012` profit
and competition honesty → `6fb2aa6` Phase 4 validation → `a92b852` monitor
wired to the API scraper → `2353cb8` `New - Open Box` accepted → `a972bc2`
dead `brand_filter` removed → `ea46093` match score persisted → `382ff0a`
CLI stores → `9fd2d8c` legacy 0.5 scores cleared → `4793c1f` Ollama timeout →
`807edbb` monitor scheduled → `8a84540` browser rows labelled → `b67be89`
Analyze supplier badge → `9a8a3bb` provenance persisted for History.

### The demand monitor (why 7d Hot Items was always empty)

`demand_data.sold_count_7d` is `None` on every path except the browser
extension's purchase-history capture, so a single search can never have a
real 7-day figure. `hunter/demand_monitor.py` appends one timestamped
`DemandSnapshot` per tracked query per run, and derives a trend **only** from
two or more observations spanning ≥24h — otherwise `unverified` with the
reason and no number at all.

- `POST /api/demand-monitor/run` — one Browse call per alert-enabled tracked
  product. ~20 products every 6h ≈ 80 calls/day against the 5,000 budget.
- `GET /api/demand-monitor/trend?query=` and `/series?query=`.

**A trend is deliberately hard to get.** Four separate refusals, each correct:
one point is not a slope; points <24h apart are not a slope; a series older
than `max_age_days` (default 7) is stale, not current; and a **zero** endpoint
is not a measurement — the Browse API returns the same empty page for a
refused request as for a quiet product, so `0` is never treated as a count.

### Six real defects found by validating rather than assuming

| Defect                                            | Found by                      | Fix                                       |
| ------------------------------------------------- | ----------------------------- | ----------------------------------------- |
| Postage dropped from every verdict                | reading `engine/decisions.py` | threaded into `calculate_profit`          |
| `£0.004` postage moved profit but printed `£0.00` | Hypothesis                    | known-ness decided on the displayed value |
| Real New labels rejected                          | real eBay fixture             | not-New first, then a `new` prefix        |
| Sold count could not name its source              | live smoke test               | `data_source` stamped on both sold paths  |
| Stale trend answered as current                   | reading `compute_trend`       | staleness window using the unused `now`   |
| Monitor recorded a false `0` for everything       | running the monitor live      | API scraper by default; 0 stored as NULL  |

That last one is worth remembering: the monitor was wired to the **HTML**
scraper, which eBay 403s, so every run stored a confident `sold_30d = 0` and
the next run's slope would have read as a collapse in demand. Four such rows
were deleted from the live table. Nothing looked wrong until the numbers were
read directly.

### Provenance now survives storage (`9a8a3bb`)

The live screen labelled every supplier row (C13: _the label is data_), but
`supplier_matches` had no provenance columns — so History replayed a saved
analysis with no label at all. A row marked on the way in lost its mark on
the way out.

- **Columns:** `provenance`, `provenance_label`, `fetch_method` on
  `SupplierMatch`; `fetch_method` is `"api"` / `"browser"` / `NULL`, and NULL
  means the row never stated it — not that it came from an API.
- **Migration:** `db.database.ensure_supplier_match_columns()`, called at
  import so it runs before anything can SELECT the column, inspect-first so
  it is a no-op after the first run. The existing table kept all 110 of its
  rows.
- **Write path:** `save_analysis_to_db` puts the three fields into the dict
  `save_supplier_match_data` passes to `SupplierMatch(**data)`; empty strings
  become `NULL` so an unmarked row cannot be read as a claim.
- **Read path:** `api/history.py` emits them; `frontend/app/history/page.tsx`
  maps them, collapsing `null` → `undefined` so `SupplierCard` renders no
  badge rather than a false `verified`.
- **Verified live**, not just in tests: a real `cordless drill` analysis
  stored `verified / Verified / browser` for two AliExpress rows and
  `/api/history/26` returned exactly those values. Rows saved before the
  column existed return `provenance: null` and render no badge — absence is
  never upgraded to a claim.

`tests/test_history_provenance_persistence.py` (10 tests) covers the
migration, the dict built at the call site, and the full round trip.

### Decisions settled (no open product questions remain)

All three questions this section used to pose are answered, and the answers
are in the code. Do not re-litigate them:

1. **`New - Open Box` — ACCEPTED as new** (`2353cb8`). eBay's real label for a
   new item in an opened box. The decision is pinned by
   `tests/test_condition_gate_real_labels.py::test_new_open_box_is_still_rejected_and_that_is_a_decision_not_a_bug`
   — the test name is the record; changing C10 means renaming it.
2. **`max competitors` threshold — STAYS ADVISORY, deliberately.** There is
   none in `config`, so the store count never gates a verdict. The user chose
   this: adding a threshold would fail products on a rule nobody set. No code
   was written, by design.
3. **Monitor cadence — 6h, scheduled** (`807edbb`). Windows Task Scheduler
   runs `backend/scripts/run_demand_monitor.cmd` every 6h. Registered by
   importing `schedule_demand_monitor.xml`, which must be written as UTF-16 —
   `schtasks /xml` rejects the UTF-8 source and PowerShell 5.1 has no
   `XmlDocument.Save(path, encoding)` overload, so convert with an
   `XmlWriterSettings` + `UnicodeEncoding($false,$true)`.
   The full exe path sits in one `<Command>` element because `schtasks /tr`
   splits at the first space in `C:\Users\Agha Moutsim\...` and silently
   produces `0x80070002`. The OS task is asserted by
   `tests/test_demand_monitor_schedule.py`, which also requires its last run
   to have returned 0.
4. **Browser-read suppliers — KEPT, provenance labelled** (`8a84540`).
   Playwright fallbacks stay; rows they produce are stamped `fetch_method`
   `"browser"` and the card shows an amber **Browser page read** chip.
   AliExpress rows are always `browser` (its API is disabled); Amazon is
   `api` only on the PA-API path.
5. **Analyze supplier rows carry the badge** (`b67be89`), via
   `stamp_scraped_product` applied once in `analysis_pipeline.py` on the same
   objects the API response and the DB save both read.
6. **History replays provenance** (`9a8a3bb`) — see below.

### Still not done / known limits

Everything this section previously listed has landed — CLI stores
(`382ff0a`), persisted `match_score` (`ea46093`), the legacy `0.5` rows
cleared (`9fd2d8c`), dead `brand_filter` removed (`a972bc2`). What remains:

- **No migration framework.** `Base.metadata.create_all` only creates missing
  TABLES, so a column added to an existing model never reaches an existing
  database. The one gap found this way is closed by
  `db.database.ensure_supplier_match_columns()`, inspect-then-ALTER, run at
  import. **The next column added needs the same treatment** — this is a
  pattern now, not a one-off, and forgetting it reproduces the exact bug it
  was written for.
- **Two supplier sources return nothing on this machine**: the AliExpress
  RapidAPI key has no search endpoint, and Amazon PA API credentials are
  missing. Both fail closed with a logged reason, not a fake row.
- **SerpApi times out intermittently** (`Read timed out` at 20s), which takes
  SerpApi, B&Q and Toolstation down together; GoDropship returns
  `ERR_EMPTY_RESPONSE`. On a bad run the supplier step can come back with few
  or zero rows and the pipeline reports that honestly rather than padding.
- **The C14 matcher rejects most generic-supplier rows**, by design. A live
  run searching `cordless drill` fetched 22 rows and kept 2 — the rest scored
  `0.35`/`no_match`. That is C14 working, not a scraper failure.
- **GitHub PAT embedded in the remote URL — rotation still overdue.**
- **`npm run lint` is broken** (Next 16, pre-existing); `tsc --noEmit` is the
  frontend gate.

---

| Consumer              | Gate function                       | Location                                                         |
| --------------------- | ----------------------------------- | ---------------------------------------------------------------- |
| Deep Search full      | `_gate_suppliers`                   | `deep_search.py` after `_verify_supplier_candidates` (~line 675) |
| Deep Search fast/Bulk | `_gate_suppliers`                   | `deep_search.py` after the supplier-append loop (~line 905)      |
| Analyze/URL-hunt      | `_score_supplier`                   | `analysis_pipeline.py` before Step 4; then sort by score, cap 7  |
| Pipeline/CLI          | `_match_gate` + `_search_suppliers` | `pipeline.py`                                                    |
| Category Hunter       | `_first_valid`                      | `hunter/supplier_lookup.py`                                      |

Shared: `config.MAX_SUPPLIERS = 7`, `engine/match.py`
(`compute_match`, `score_candidates`, `filter_matches`, `assign_match`).

**Reference title used for scoring:** `ebay_product.title` (Analyze),
`result.product_name or query` (Deep Search), `product.title` (Hunter/Pipeline).
Brand is deliberately **empty** in Analyze — supplier search runs before the
LLM, and an unknown brand scores neutrally rather than as a mismatch.

---

## 6. Rules of engagement (learned the hard way — follow these)

1. **Report after every change.** User explicitly asked: _"after every changes
   give me what you have changed."_
2. **Change docs are `.md` files, on request only.** `docs/P2-changes.md` is
   the precedent and the quality bar.
3. **Delegate simple/medium work to sub-agents; keep complex work.**
   Complex = matcher design, gate wiring, spec interpretation. Simple =
   test suites, export columns, frontend badges, scraper field capture.
4. **Partition file ownership to avoid collisions** — state an explicit
   allow-list per agent (`backend/scrapers/**` only, `frontend/**` only,
   `tests/test_X.py` only). Tell agents to _report_ bugs, never fix them.
5. **Baseline before delegating:** run the suite, quote `539 passed` in the
   prompt, require the agent to report exact counts back. A drop below
   baseline is a failure.
6. **Never commit** unless explicitly told. Nothing has been committed since
   `cf6e094`.
7. **Do not hardcode keys.** Read `os.getenv(...)`. `.env` exists, is
   gitignored and untracked — never print it.
8. Sub-agents sometimes return a _plan_ instead of doing the work (happened
   with `test_match.py`). If a task result is a plan, resume the same
   `task_id` and say "approved, write the file now."
9. Sub-agents hit **rate limits** — if a task fails with `Rate limit
exceeded`, retry later; nothing was written.

---

## 7. File map (all committed — `git log --oneline` is the record)

**New since the original handoff:**

```
backend/api/provenance_block.py      shared provenance-block builder for all responses
backend/engine/condition_gate.py     C10
backend/engine/match.py              C14  <- most recently written, most load-bearing
backend/engine/provenance.py         C13
backend/engine/source_type.py        supplier type classifier (leaf)
backend/engine/stores.py             C11
backend/scrapers/availability.py     stock/shipping text parsers (leaf)
backend/scrapers/serpapi_discovery.py  P4a discovery (NOT yet wired)
docs/P2-changes.md                   approved change doc
frontend/lib/provenance.ts           normalizeProvenance contract
frontend/components/ui/ProvenanceBadge.tsx
frontend/components/ui/ProvenanceSelect.tsx
frontend/components/ui/MatchBadge.tsx    match tier + stock/shipping copy
frontend/components/EbayStoresCard.tsx
tests/test_match.py                  187 tests
tests/test_match_wiring.py            67 tests
tests/test_serpapi_discovery.py       32 tests  (P4 discovery, zero network)
tests/test_phash_wiring.py            30 tests  (C14 image signal, zero network)
tests/test_provenance.py             87 tests
tests/test_store_wiring.py           42 tests
tests/test_stores.py                 62 tests
```

**Heavily modified:** `CONSTRAINTS.md`, `backend/{analysis_pipeline,deep_search,
pipeline,config,main}.py`, `backend/api/{analyze,bulk,deep_search,filters,
hunter}.py`, `backend/export/{format,csv_export}.py`,
`backend/hunter/{category_scan,demand_check,profit_calc,report,supplier_lookup}.py`,
`backend/llm/prompts.py`, `backend/scrapers/*`, `backend/suppliers.json`,
`frontend/app/*/page.tsx`, `frontend/components/*`, `frontend/lib/types.ts`.

**Test suites (do not edit when you own only one file):**
`test_match.py` (187), `test_match_wiring.py` (67), `test_provenance.py` (87),
`test_stores.py` (62), `test_store_wiring.py` (42),
`test_serpapi_discovery.py` (32) and `test_phash_wiring.py` (30) are both
zero network + pre-existing ~164 → **671 for those seven alone** (the whole
suite is **1163** — see §1). Added since: `test_demand_monitor.py`,
`test_demand_monitor_schedule.py` (asserts the OS task, skips if absent),
`test_fetch_method.py`, `test_analyze_provenance_stamp.py`,
`test_history_provenance_persistence.py`, `test_match_score_persistence.py`,
`test_range_storage.py`, `test_clear_legacy_match_scores.py`.

---

## 8. Secrets & config

`.env` (gitignored, untracked) — **never print, never commit:**

- `SERPAPI_KEY` — verified working with `gl=uk&hl=en`, `engine=google_shopping`
- RapidAPI key for `aliexpress-datahub.p.rapidapi.com` (only
  `/store_categories` + `/item_detail` — **no search endpoint**)
- RapidAPI key for `real-time-amazon-data.p.rapidapi.com` — `/search` returns
  0 results, **unusable**
- Known mismatches (deliberately left): `scrapers/aliexpress.py:55` targets
  `aliexpress-api.p.rapidapi.com` (wrong host, now fails closed);
  `scrapers/amazon_uk.py` expects AWS PA API (fails closed)
- Ollama at `http://localhost:11434` model `llama3.1:8b` — LLM analysis is
  **optional**; every path degrades to unverified defaults when it is down.

---

## 9. Suggested first three moves in the new session

1. **Verify:** run §1. Expect `1163 passed`, `tsc` exit 0. If not, stop and
   diagnose — do not build on a broken baseline.
2. **The decision queue is empty.** All six product questions are settled and
   recorded in §4.5 — do not re-open `New - Open Box`, the competitor
   threshold, monitor cadence, Playwright labelling, the Analyze badge or
   History provenance. P4 (condition gate, stores, provenance, matcher,
   discovery, pHash) was already closed; the commit chain in §4.5 shows
   everything since.
3. **The real remaining work is environmental, not architectural:** rotate the
   GitHub PAT out of the remote URL, and decide whether to fix the supplier
   coverage gaps (AliExpress key with no search endpoint, Amazon PA API
   credentials missing, intermittent SerpApi timeouts) — all three fail
   closed today with a logged reason, so nothing is lying about them.

Change docs are created **on request only**; ask before writing any.
