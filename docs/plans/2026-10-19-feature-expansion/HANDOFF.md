# Handoff - current state

Last updated: 2026-10-29, AU Category Hunter (Phase E4) landed; next is AU Phase E5 Fee Calculator.
Read this first, then `implementation.md` (phase specs and rules) and `design.md` (surfaces).

## Where the work stands

The ten-feature expansion lives in this folder. Baseline phases 1 and 2 are complete.

| Phase | Scope                         | Status                                  |
| ----- | ----------------------------- | --------------------------------------- |
| A     | Passive capture (extension)   | shipped - awaiting one real-browser run |
| B     | Rich field persistence        | shipped                                 |
| C     | Verified-first and Sources    | shipped                                 |
| D     | Fee and break-even calculator | shipped, closed at `605b9b1`            |
| E     | Alerts and saved searches     | shipped, closed at `19f7578`            |
| F     | Title helper                  | shipped, closed at `5fd581f`            |
| G     | Listing age and churn         | shipped, closed at `1b42dce`            |
| H     | Seller footprint              | shipped, closed at `79c5673`            |
| I     | Own-sales P&L and feedback    | shipped, code closed at `8f3f753`       |
| J     | Marketplace expansion         | shipped, code closed at `b5e7a59`       |

Phases ship as a small number of well-scoped commits, committed and pushed as each lands,
with evidence in the phase's "Shipped" block in `implementation.md`. The AU thread uses
three commits per phase.

## Next move

Phase J is implemented and verified; the ten planned phases are complete. The active work is
the AU market thread below: **Phase E2 (Deep Search) just closed**, and **Phase E3 (Bulk) is
next**. The older user-owned list under "Pending items that need the user's word" and the two
exposed credentials remain open. There is no Phase K.

The one live-browser gap from Phase A remains: the extension is loaded and reaches the backend,
but it has not completed a successful capture. It is a verification gap, not a missing phase.

## AU market build (new thread, 2026-10-27)

The Australian build is a separate six-phase thread on top of the ten shipped phases. It is
**not** the same "Phase A/B" labels used in the table above.

- **Phase A (fee research) - complete.** `docs/au-market/fee-research.md` transcribes eBay
  Australia's own Pro and free-selling pages, with four Wayback capture IDs and the pages' own
  "Last updated" lines. Ten commits, `bfe5016` to `1f195b3`. No third-party calculator number
  is a source. The four published worked examples reproduce.
- **Phase B (AU fee card) - complete.** `backend/engine/fees.py` now carries
  `au-rate-card-2026-10-09`, registered in `FEE_TABLES` and selectable by key. It has both
  seller branches: eBay Pro (four plans, Tier 1-4 rates, per-order fee, over-$4,000 step, 1.1%
  international fee) and free selling (0% FVF, no assumed per-order fee, 3% international fee,
  label mandate). Individual is the AU default; Pro Starter is the business default. GST is
  displayed inclusive and never added as a line. Ambiguous parent categories 625/293/172176/
  15032/1249 resolve to the stated Tier 2 default with `known=False`. The label rule is a
  predicate (`fees.label_required`), not a fee. Implementation notes:
  `docs/au-market/fee-card.md`; pins: `tests/test_fees_au.py` and
  `tests/test_fees_au_acceptance.py`. Ten commits, ending with this handoff update.
- **Phase C - complete (three commits).** `EBAY_AU` now carries
  `fee_table: "au-rate-card-2026-10-09"` and `fee_calculator_ready: False`. The public
  selector reports `fee_table: None` plus `fee_table_registered` and the registered-card
  sentence, so "card on file" cannot be mistaken for "ready to price". Each market has
  seller defaults (UK business/UK; AU Individual/AU, Pro Starter for a business sale), and
  the fee API resolves the market's card, refuses a foreign-currency card, and takes
  `seller_plan`/`buyer_region` from the market rather than the UK profile. Analyze, Deep
  Search, Bulk, Category Hunter and the fee calculator remain locked for AU until Phase E.
  Details: `docs/au-market/market-config.md`; pins: `tests/test_au_market_config.py`.
- **Phase D - complete (three commits).** The supplier bench is now a market property:
  UK keeps AliExpress/CJ/B&Q/Toolstation/Joybuy; AU is AliExpress + CJ only. SerpApi
  discovery is scoped to the bench and to Google Australia (`Australia` / `au`), Category
  Hunter lookup skips Joybuy for AU, and `search_all_suppliers` instantiates only the bench's
  scrapers. Analyze now gates on `fee_calculator_ready`, not the presence of a registered
  card, so the AU card does not accidentally run the UK pipeline. Details:
  `docs/au-market/supplier-bench.md`; pins: `tests/test_au_supplier_bench.py` plus the
  discovery/Hunter tests. **Currency policy:** AliGate is now scoped per market (AU/AUD for
  AU), and CJ's USD `sellPrice` is tagged USD and excluded from AUD comparisons rather than
  converted. The UK keeps its historical USD->GBP 0.79 path.
- **Phase E1 - complete (three commits).** Analyze is unlocked for AU in AUD while the
  standalone fee calculator stays locked. `analyze_ready` is a separate switch from
  `fee_calculator_ready`; AU uses its own `A$0.99-A$50.00` band and 15/10 demand floors,
  eBay Australia is searched with the explicit AUD band, AliGate is asked for AU/AUD/en_AU,
  AUD rows pass through, and CJ's USD rows are tagged and excluded with a sentence rather
  than converted. AU results are not written to History. Details:
  `docs/au-market/analyze.md`; pins: `tests/test_au_currency.py`,
  `tests/test_au_analyze.py`, plus the updated market/route tests.
- **Phase E2 - complete (three commits).** Deep Search is unlocked through `analyze_ready`,
  not a UK-only gate. The sold scraper follows `EBAY_AU` (AUD, ebay.com.au,
  `deliveryCountry:AU`, `priceCurrency:AUD`), the run uses the AUD band and 15/10 floors, the
  LLM prompt asks for A$, and web/SerpApi queries are scoped to the AU bench (AliExpress + CJ).
  Supplier rows carry their own currency; a USD row is excluded with a sentence, never
  converted, and an untagged row is not assumed to be AUD. Job records and every poll payload
  carry `marketplace`/`currency`/`currency_symbol`. The UI reads the marketplace, hides the AU
  `RangeControl`, formats every amount in its own currency, clears a stale result on a market
  switch, and shows a lock notice for a market without `analyze_ready`. Checks: backend
  **1963 passed, 9 deselected**; frontend **216 tests across 16 files**, typecheck and
  production build clean. Details: `docs/au-market/deep-search.md`; pins:
  `tests/test_au_deep_search.py`, updated `tests/test_markets.py`, and the unchanged UK
  job/provenance/store pins.
- **Phase E3 - complete (three commits).** Bulk is unlocked through `analyze_ready`, so AU
  runs `deep_search_fast()` in AUD while the fee calculator stays locked. `POST /api/bulk`
  refuses a market without a card or bench with "not enabled", returns
  `marketplace`/`currency`/`currency_symbol`, and passes `marketplace=` to
  `deep_search_fast()` only for non-UK markets (UK keeps the one-argument call). The fast
  path keeps its AUD band, floors, sold site, bench and currency boundary; a USD supplier
  row is excluded with a sentence, never converted. The UI reads the marketplace, shows a
  lock notice, disables the form for unready markets, formats every amount in its own
  currency, and clears a stale result on a market switch. Checks: backend **1963 passed,
  9 deselected** plus `tests/test_au_bulk.py` (3 passed); frontend typecheck clean.
  Details: `docs/au-market/bulk.md`; pins: `tests/test_au_bulk.py`.
- **Phase E4 - complete (three commits).** Category Hunter is unlocked through
  `analyze_ready`, so AU scans and looks up suppliers in AUD. `POST /api/hunter/scan` and
  `POST /api/hunter/lookup` refuse a market without a card or bench with "not enabled",
  return `marketplace`/`currency`/`currency_symbol`, and carry `marketplace=` through
  scan, demand check, supplier lookup and profit calculation (UK keeps its historical
  call shapes). Scan uses the market site, marketplace id, delivery country and price
  currency; AU uses its band and demand floors; direct CJ/AliExpress scrapers receive
  the market; profit uses the AU fee table and `DecisionEngine(..., marketplace=...)`.
  The UI reads the marketplace, uses the AU band, shows a lock notice, disables scan and
  lookup for unready markets, formats amounts in their own currency, and clears stale
  results on a market switch. Checks: backend **1966 passed, 9 deselected** plus
  `tests/test_au_hunter.py` (6 passed); frontend typecheck clean. Details:
  `docs/au-market/hunter.md`; pins: `tests/test_au_hunter.py`. **Next:** Phase E5
  Fee Calculator, then Phase F UI + docs. Three commits per phase, a short report at each
  phase end.

Still open from the older thread: the live-browser capture gap, the history migration spec,
the four redundant `listing_observations` rows on `266923866336`, Deep Search/batch observation
wiring, the seed button, and rotating the two exposed credentials (GitHub token, ScrapingBee
key). None is a Phase D blocker.

## Live state — AliExpress supplier discovery, measured 2026-10-23

### The old listing is gone; AliGate is wired and verified

- The previous RapidAPI listing `aliexpress-api.p.rapidapi.com` was **removed** (its page
  404s into RapidAPI's generic hub, which also explains the earlier "not subscribed" 403).
- The seam now targets **AliGate** (`aligate-aliexpress-data-api.p.rapidapi.com`,
  `GET /api/v2/search/text`): free Basic tier — **100 requests/month hard cap**, 1 req/sec.
  The key belongs to the same RapidAPI app; the user subscribed to AliGate under it and
  rotated the key after it appeared in chat/screenshot twice. Host and market scope are
  `.env`-overridable: `RAPIDAPI_HOST`, `ALIGATE_COUNTRY`/`ALIGATE_CURRENCY`/`ALIGATE_LOCALE`
  (defaults `GB`/`GBP`/`en_GB`, accepted by the gateway live).
- Every unknown was settled from the gateway's own answers, never guessed:
  `keywords` → renamed to `query` after `meta.error "query is required"`; the row list sits
  under `item.products` (found via the truncated body snapshot the connector now logs on an
  unparsed HTTP 200); `meta.code: 409 "please try again"` earned one bounded retry.
- End-to-end live run (`Analyzer` query "stainless steel water bottle 500ml"): **7 supplier
  rows** — 3 B&Q browser rows plus **4 AliExpress rows with `fetch_method="api"`**
  (£6.00–£11.59, GBP-tagged in the payload, passed through unconverted), scored, ranked and
  persisted through the sourcing standard. USD- or untagged-currency rows still convert at
  the fixed 0.79 rate; any other stated currency is skipped rather than ranked as GBP.
- Known provider quirk: some long branded listing titles (e.g. the "Vodafone … 24/12h"
  bottle) return a persistent 409 even after the retry — one provider-side failure the
  honesty layer absorbs ("no suppliers" with the fallback WARN), not an app defect. Quota
  note: supplier search spends 1–2 of the 100 monthly requests per keyword; bulk/deep-search
  runs will consume it faster. AliGate Pro ($6.99/mo, 350/day) is the upgrade path if needed.

### Suite hermeticity (same session)

- `config.py` `load_dotenv()`s at import, so the pytest process carried the user's real
  `RAPIDAPI_KEY`. An autouse `_no_live_rapidapi_key` fixture in `tests/conftest.py` now
  deletes it (same leak class as the Joybuy guard and the hermetic price band); tests that
  want a key monkeypatch their own, which wins. One suite run had already burned a live
  metered request before the guard landed.
- Backend suite: **1775 passed, 9 deselected**. Commits this thread: `cbd23b0`, `0b34c6f`,
  `ab7f505`, `4c8d5ff`, `a481158` — all pushed.

### Honest empty-search error (same day)

- The user's Analyze on a misspelt query ("black gloss tire coting") showed "eBay requires
  API keys" although `.env` has them. The Step-1 zero-result branch claimed a cause it
  could not know: `ebay.search()` returns `[]` for missing keys AND for a genuine empty
  answer AND for a swallowed network error. Live probe settled it — eBay returned
  `total: 0` for the misspelt phrase with and without filters, while the corrected words
  ("black gloss tire coating", "tyre coating") return ~240/234 listings. The branch now
  says "requires API keys" only when the credentials are truly absent, and otherwise
  names the honest truth: eBay returned no listings for that query with the active
  filters (band + New-only) — try different or fewer words, spelling, or retry.

## Live state

### Phase J, measured 2026-10-21

- `GET /api/markets` returns **5** markets (`EBAY_GB`, `EBAY_US`, `EBAY_DE`,
  `EBAY_AU`, `EBAY_CA`) with `deals_http_status: 200` and a `deals_checked_at`
  of **2026-10-21** on every one. Only `EBAY_GB` has a fee table; the other four
  return `fee_table: null`. `EBAY_IE` is absent because its `/deals` URL went
  into eBay's splashui challenge instead of a deals board.
- Non-UK Analyze, one live US query (`"usb c cable"`): first listing **$0.99**,
  source `ebay_us`; demand **50 active listings**, average active price
  **$11.3438**, `sold_count_30d: null`. No supplier matches, profit or verdict.
  Two sentences say it is search-only and that no History row was written.
  This is one query and one listing, not a US market sample.
- Deals page reachability: one GET per URL returned HTTP 200 and cards were
  read from the returned page - **GB 72, US 21, DE 80, AU 76, CA 57**. eBay US
  redirects `/deals` to `/globaldeals`; its cards use the nested shape. These
  are page observations, not sales counts.
- `deal_items`: **94** rows - 73 UK rows written before Phase J and 21 US rows
  from the live `POST /api/deals/refresh` (all 21 priced, all `USD`; first
  label `$38.91`; `last_refresh_error: null`). The UK board still returns its
  73 rows. The table now has `UNIQUE(marketplace, listing_id)`, migrated from
  the old global unique without losing the 73 UK rows; the migration was run
  twice on a copy first.
- Non-UK refusals were exercised live: `GET /api/fees/table` and
  `POST /api/deep-search` with `X-Ebay-Marketplace: EBAY_US` both returned
  **422** and the UK-only sentence. No non-UK fee or profit figure was
  produced, and no non-UK `listing_observations` were written.
- Checks: backend **1712 passed, 9 deselected**; frontend **216 tests across
  16 files**, typecheck clean; production build **18 route rows**.

### Sourcing standard, measured 2026-10-21

- Shared sourcing policy: `backend/engine/sourcing.py` plus `tests/test_sourcing.py`,
  `tests/test_sourcing_consistency.py`, `tests/test_aliexpress_sourcing.py` and
  `tests/test_sourcing_persistence.py`.
- Analyze, Deep Search, Bulk and Category Hunter all rank suppliers through the
  same policy. Supplier rows carry stock, shipping, review, AliExpress Standard
  Shipping, total landed cost, preferred/eligible flags, reasons and score.
- `SupplierMatch` now stores the sourcing evidence; Analyze persists it and
  History replays it.
- Frontend supplier cards and Analyze, Deep Search, Bulk and Hunter surfaces
  render the sourcing evidence.
- The policy refuses to treat missing price, stock, shipping, review or standard
  shipping as a pass. `total_landed_cost` is null when shipping is unknown.
- Checks: backend **1748 passed, 9 deselected**; frontend **216 tests across
  16 files**, typecheck clean; production build **18 route rows**.

### Earlier measurements, 2026-10-20

- `price_alerts`: 1 real row - cordless drill, query lane, average asking price £22.66 →
  £22.57, unread.
- `saved_searches` 0, `search_results` 0 (a live throwaway run was deleted after capturing
  its refusal).
- `price_history`: 2 rows, both 0.0 (failed eBay item reads).
- `demand_snapshots`: **68** as of the Phase J close (62 at the earlier Phase I measurement).
  The successful demand-monitor re-run that cleared an interrupted last-result added one pair
  of rows with no sold count; it is not new sold evidence. 26 rows carry a `sold_30d` figure
  and 32 an average price; `sold_7d` is unread in all 68.
- Tracked products: Dell V100 (eBay 600, target 550.9, supplier 0) and cordless drill
  (no prices).
- `listing_observations`: **487** (386 before Phase G; the two live Analyze runs added 101).
  Phase J's non-UK deals refresh skipped this table because it is not marketplace-keyed.
- `query_observations`: **2**, both the "garden hose" lane, 5 listings each, same Browse filter
  and limit, 34 seconds apart. Churn currently reports 1 missing: listing `318706761430`,
  last seen `2026-10-20T14:21:32Z`, status `no_longer_listed`. This is a 5-listing sample, not
  a market rate. There is no backfill: older `listing_observations` rows have no query
  attribution.
- Age route sample: listing `157783405092` is **209 days** old from eBay's
  `2026-03-25T08:12:22Z` creation date; this app first saw it on 2026-10-20.
- Seller footprint, measured 2026-10-20: `GET /api/sellers/agprefect_09?query=garden%20hose`
  returns 1 observed listing from the latest **5-listing** sample (2 stored observations),
  feedback **99.9% (27,956)**, `BUSINESS`, `GB - WR4***`, 100% New, GBP 16.99, 209 days.
  `GET /api/sellers/mountainwarehouse` returns 8 observed listings from 32 readings, feedback
  **99.8% (214,302)**, `BUSINESS`, `GB - PE3***`, 100% New with tags, GBP 13.99 - GBP 99.99,
  median GBP 22.99, 42-2446 days. Neither is a seller-wide census. The route is read-only and
  writes no table.
- There are **252 distinct seller names** in the 487 `listing_observations`; the top observed
  seller is `mountainwarehouse` with 32 readings across 8 listings.
- Title helper: no table writes. A live `GET /api/titles?q=garden hose` read 50 listings on
  2026-10-20; a deliberately meaningless query returned a measured zero with a sentence.
- Own sales, measured 2026-10-20: `sales` **0** rows and `monthly_stats` **0** rows. No demo sale
  was inserted. The live `monthly_stats` table has only `uq_monthly_stats_year_month` on
  `(year, month)`. `GET /api/sales/summary?days=30&months=6` returns revenue **0**, profit
  **0.0**, average margin `null`, six monthly points and `user_declared: true`.
- C14 feedback, measured 2026-10-20: `supplier_matches` has **155** rows, **45** with a
  `match_score` across **9** products; **110** rows are unscored and excluded. At a proposed
  confirmed threshold of **0.70** (shown threshold unchanged at 0.45), confirmed rows fall
  **23 → 22** and **1** stored row moves verified → unverified. `changes_applied` is `false`.
  The sample is 45 scored rows, not the matcher's full candidate set; rows dropped before
  storage cannot be replayed.

## Blockers - do not work around by inventing a number

- eBay `/itm/` pages return 403 through the scraper; Marketplace Insights returns 403. The
  item-lane alerts stay silent until tracker checks can read pages.
- SerpApi is at 0/250 until **2026-11-08**. Supplier discovery and live saved-search runs
  may legitimately refuse with "no real supplier price was found".
- The extension is installed and its popup reaches the API, but no capture has been stored.
  The current live failure is `Could not fetch the purchase-history page: Failed to fetch`;
  eBay's `/bin/purchaseHistory?item=` endpoint returns its splashui browser challenge, and the
  profile used for the run was signed out. Sign in to eBay UK, open the purchase-history URL
  directly, then retry. `items_captured` is still **1**. The ten-capture acceptance target is
  **11** only if every new page yields a parseable capture; do not invent rows to reach it.

## Security - outstanding user action

- The GitHub token used in earlier sessions was exposed and **must be rotated**. It is not
  reused.
- Git pushes work as of 2026-10-20 through a refreshed `gh` OAuth token with `repo` scope
  (account `agha-moutsim`); a plain `git push` succeeded. Never put a token in a commit, a
  tracked file, or a shell command that is logged.
- The ScrapingBee key was exposed too. Rotate it in `backend/.env` (never committed).

## How to run and verify

- Servers: backend `uvicorn main:app --host 127.0.0.1 --port 8000` from `backend/`
  (logs `.logs/backend.log`); frontend `next start -p 3000` from `frontend/`
  (`frontend/.logs-web.log`). `start.ps1` / `stop.ps1` exist.
- Backend tests from the repo root: `python -m pytest tests/ -q` (~3.5 min; expect 1712 passed,
  9 deselected).
- Frontend from `frontend/`: `npm run typecheck`, `npx vitest run` (216 tests across 16 files),
  `npm run build` (18 route rows including `_not-found`; `/sales`, `/churn`, `/titles` and
  dynamic `/sellers/[username]` are four of them).
- The pre-commit hook runs prettier, typecheck and the full backend suite. A failed hook
  leaves no commit - always check `git log --oneline -1` after committing.
- Commit identity: `Agha Moutsim <131957706+agha-moutsim@users.noreply.github.com>`.
- The scheduled task "eBayHunter Alerts" runs hourly (`PT1H`) at zero Browse cost; the
  deals board runs hourly too.

## Standing product rules

- Real, measured data only. Never fabricate a price, fee, margin or count; absent stays
  `None`, and a refusal carries a sentence.
- Scope stays on the ten new features, not the whole product.
- An alert names the two values it compared - no comparison, no row.
- Saved-search runs state their budget: one Browse call per run, at most ten runs per pass.
- Marketplace statistics are never called "sold" unless verified.
- UI is elegant, professional and premium; brand visuals are user-generated.

## Pending items that need the user's word

- The history migration offer.
- 4 redundant `listing_observations` rows on listing `266923866336`.
- Deep Search / batch demand-check observation wiring decision.
- The seed button deferred from Phase A.
