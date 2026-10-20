# Handoff - current state

Last updated: 2026-10-20, at the close of Phase F.
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
| G     | Listing age and churn         | not started                             |
| H     | Seller footprint              | not started                             |
| I     | Own-sales P&L and feedback    | not started                             |
| J     | Marketplace expansion         | not started                             |

Phases ship as roughly ten commits: one well-scoped change each, committed and pushed as it
lands, with evidence in the phase's "Shipped" block in `implementation.md`.

## Next move

Phase G - listing age and churn (`implementation.md` Phase G, `design.md` §3.8). Build
`backend/engine/listing_age.py` (age from eBay's `item_creation_date`; churn by diffing
consecutive observations per query), `GET /api/observations/{listing_id}` and
`GET /api/observations/churn?query=`, the age chip, and the `/churn` page. Rules: fewer than
two observations means no churn claim, and the copy is "no longer listed" with the last-seen
date - never "sold". A test must pin that the word "sold" does not appear in the module.

## Live state, measured 2026-10-20

- `price_alerts`: 1 real row - cordless drill, query lane, average asking price £22.66 →
  £22.57, unread.
- `saved_searches` 0, `search_results` 0 (a live throwaway run was deleted after capturing
  its refusal).
- `price_history`: 2 rows, both 0.0 (failed eBay item reads).
- `demand_snapshots`: 62, with a real `avg_price` series for "cordless drill".
- Tracked products: Dell V100 (eBay 600, target 550.9, supplier 0) and cordless drill
  (no prices).
- `listing_observations`: 386. `deal_items`: 73, refreshed hourly - do not disturb.
- Title helper: no table writes. A live `GET /api/titles?q=garden hose` read 50 listings on
  2026-10-20; a deliberately meaningless query returned a measured zero with a sentence.

## Blockers - do not work around by inventing a number

- eBay `/itm/` pages return 403 through the scraper; Marketplace Insights returns 403. The
  item-lane alerts stay silent until tracker checks can read pages.
- SerpApi is at 0/250 until **2026-11-08**. Supplier discovery and live saved-search runs
  may legitimately refuse with "no real supplier price was found".
- The extension has never run in a real browser. The user must reload v1.1.1 on
  `chrome://extensions`, open ten listings, then `GET /api/extension/status` should report
  `items_captured: 11`.

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
- Backend tests from the repo root: `python -m pytest tests/ -q` (~3 min; expect ~1585
  passed, 9 deselected).
- Frontend from `frontend/`: `npm run typecheck`, `npx vitest run` (161 tests),
  `npm run build` (15 route rows including `_not-found`; `/titles` is one of them).
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
