# Constraints

The rules these features must obey. Most were established by measurement and cost this project
real time to learn; they are not preferences.

---

## 1. Honesty rules (non-negotiable)

Referenced in code as C1, C4 and C13.

| Rule | Statement                                                                                                                                                                         |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1   | Never fabricate a marketplace value. If it was not measured, it is not shown.                                                                                                     |
| C4   | A verified 7-day sale figure requires a logged-in purchase-history capture. Nothing else produces one.                                                                            |
| C13  | Provenance travels with the row into storage, or a replayed History screen shows unlabelled numbers while the live screen shows labelled ones. The LLM is never a source of fact. |
| C14  | Matcher thresholds are calibrated. Do not loosen them to make a feature look better.                                                                                              |

Concrete prohibitions that follow:

- **Never** print a sold count, units-sold figure, revenue estimate, sell-through percentage or
  search-volume number that did not come from a measurement in this system.
- **A delisting is not a sale.** A listing present earlier and absent now is "no longer listed".
  The two are indistinguishable from outside, so the weaker claim is the only permitted one.
- **Supply is never demand.** A count of live listings may not be labelled popularity, best-seller,
  trending or demand. This is the mislabelling that commit `842e556` and `e3fccad` existed to undo.
- **Unknown is a state, not a blank.** Every new numeric field must be nullable, and the UI must
  render "not measured" rather than an empty cell or a zero.
- **No popularity-shaped column may be added** without a test preventing it. The existing pattern
  is `TestTheTableCannotHoldAPopularityClaim` in `tests/test_deals.py`.
- Any new numeric field needs a provenance stamp and a human-readable `data_source`-style sentence
  explaining what produced it.

---

## 2. What is measurably unavailable (do not re-attempt)

Established by direct testing. Re-testing wastes hours and produces the same answer.

| Route                                                 | Result                                                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Marketplace Insights API                              | HTTP 403, scope `buy.marketplace.insights` not granted. Closed to new users.                                  |
| Deals API                                             | HTTP 400, scope not granted                                                                                   |
| `getMostWatchedItems` (Merchandising)                 | Deprecated 2024-07-29, decommissioned 2025-01-06                                                              |
| `findCompletedItems` (Finding)                        | Decommissioned 2025-02-04                                                                                     |
| Browse API `watchCount` / `quantitySold` / `bidCount` | Not returned at all                                                                                           |
| Browse API `sort`                                     | Silently ignored for 16 of 19 values tested. Only `newlyListed`, `endingSoonest`, `-price` genuinely reorder. |
| `ebay.co.uk/trending`                                 | HTTP 403                                                                                                      |
| `ebay.co.uk/b/Best-Selling/...`                       | HTTP 403                                                                                                      |
| `ebay.co.uk/sch/i.html` (active and sold)             | HTTP 403 direct, HTTP 500 via ScrapingBee                                                                     |
| `ebay.co.uk/itm/<id>`                                 | HTTP 403 for live-priced and unpriced listings alike                                                          |
| `/deals/ajax/listings`                                | HTTP 200 with a zero-byte body for every param shape tried. Params are assembled client-side.                 |

Reachable without credits: `/deals` (73 unique listings) and the six `/deals/featured/<slug>`
pages (24 each; union with the main page is 192 unique, overlap 25). The 6,038 advertised in the
page payload sits behind the AJAX call above and is **not** reachable.

**Do not build a feature whose honesty depends on any route in the first table.**

---

## 3. Quota budgets

eBay Browse API allowance is **5,000 calls per day**, shared by every feature.

```
measured cost       1.48 calls per listing priced      (108 calls for 73 deal cards)
deals refresh       ~2,600/day at 73 items, hourly
expanding to 192    ~284 calls per refresh; hourly would be ~6,820/day -> over budget
                    every 2h ~3,410/day   every 3h ~2,273/day
```

Decision on record: the deals board stays at **73 items, hourly**. Do not change that.

Therefore any new Browse-backed feature must:

- state its per-run call cost before being built;
- default to a cadence that keeps total daily usage meaningfully under 5,000;
- degrade gracefully on HTTP 429 - the existing `QuotaExhausted` signal means "stop asking", not
  "retry harder";
- never fetch on a read route. The API route is a pure read plus an opt-in background trigger;
  fetching happens in scheduled jobs.

SerpApi: **0 of 250 calls remaining**, resets 2026-11-08. Supplier discovery is dark until then.
Do not design anything that assumes supplier data is available before that date.

---

## 4. Extension safety and ToS boundary

The extension acts inside the user's **personal, logged-in eBay account**. That account is the
only thing that can produce verified sold data, so it must not be risked.

Permitted:

- Capturing the purchase-history page for an item the user is **already viewing**.
- A dedupe window so the same item is not captured repeatedly.
- A user-initiated, human-paced seed queue for a small explicit list of item URLs.
- A quiet mode to suspend capture entirely.

Not permitted:

- Automated navigation or sequence-opening of item ids at machine speed.
- Background crawling of purchase-history URLs not reached by the user.
- Any pattern whose rate is bounded by code rather than by human browsing.

A ban on that account destroys the entire data strategy. When in doubt, capture less.

---

## 5. Architectural constraints

- **Read routes never fetch.** `GET` returns stored data; a separate explicit trigger refreshes.
- **`NULL` means "not read".** Never overload it as zero or as "not applicable". Prices and
  amounts already follow this; the deals board renders "See price on eBay" for an unread price.
- **Sold and active never share a column.** They are different measurements with different
  meanings. The split into `sold_*` and `active_*` columns was deliberate (`e3fccad`).
- **Upsert by natural key where a refresh replaces content**, so primary keys survive and the
  client does not remount. `deal_items` does this by `listing_id`.
- **Tables self-heal.** `create_all` creates missing tables only; it never alters existing ones.
  New columns are added by `ensure_*` helpers in `backend/db/database.py`, called on import, and
  must be idempotent.
- **Naive UTC in the backend.** Mixing aware and naive datetimes raises on subtraction. Convert on
  the client (`asUtc()` in `DealsBoard.tsx` is the precedent).
- **One implementation per calculation.** A fee figure computed in the pipeline and again in the
  UI will disagree. Phase D exists to collapse these into one function.

---

## 6. Process constraints

- **One well-scoped change per commit.** No mixed-purpose commits.
- **Report what changed after every change.**
- **Run the suite by hand before pushing** - there are no working git hooks.
  ```
  cd backend && python -m pytest tests/ -q          (expect 1203 passed, 9 deselected)
  cd frontend && npx vitest run                    (expect 54 passed)
  cd frontend && npx tsc --noEmit                  (expect exit 0)
  npm --prefix frontend run build                  (expect 11 routes)
  ```
- **Commit author must be** `Agha Moutsim <131957706+agha-moutsim@users.noreply.github.com>`,
  author and committer both, or the contribution graph does not render.
- **Push needs the inline credential-helper override**; the keyring token lacks repo access.
- **Commit subjects are imperative and explain why**, e.g. "Stop counting live listings as sold
  sales". No conventional-commit prefixes are used in this repo.
- **Brand assets come from the user.** Do not generate logos or app screenshots.
- **UI must be elegant, professional, modern and premium** - matched to the existing brand kit,
  not to a generic dashboard look.

---

## 7. Environment gotchas

- `grep` is not on PATH - use `Select-String`.
- The `edit` tool fails on files containing mojibake; patch those with a Python script instead.
- PowerShell inline `python -c` with quotes breaks; write a here-string to a file first.
- `Path.write_text(encoding="utf-8")` writes no BOM; PowerShell `Out-File -Encoding utf8` does.
  Use `[System.IO.File]::WriteAllText($p, $s, (New-Object System.Text.UTF8Encoding $false))`.
- A dirty `backend/data/custom_filters.json` fails about 10 price-band tests. Restore it first.
- A stray `inspect.py` in `%TEMP%\opencode` shadows the stdlib - run helper scripts from a
  subdirectory such as `%TEMP%\opencode\<name>\`.
- Stale processes hold :3000/:8000. Kill matching `*ebay-hunter*` owners and remove
  `frontend\.next\dev` before restarting, or Next refuses to start.
