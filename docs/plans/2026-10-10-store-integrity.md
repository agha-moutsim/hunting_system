# Store integrity, runtime, and dashboard plan

Tracked here so the work survives a broken session. One row per phase; update
`Status` as each phase lands. Every phase is committed and pushed separately.

Budget: **20 eBay calls total** (8 baseline + 12 verification). Running total
is recorded in the report at the bottom.

## Root causes (established, not hypothesised)

### Invalid eBay store links — NOT the LLM

The LLM never participates in store identity. `backend/engine/stores.py` builds
stores purely from `seller.username` values read off real eBay responses.

The defect is a **conflated domain concept**. eBay has two distinct identifiers:

| Concept            | Source                            | Valid URL form    |
| ------------------ | --------------------------------- | ----------------- |
| Seller **user ID** | Browse API `item.seller.username` | `/usr/{username}` |
| Store **URL slug** | vanity name on the listing page   | `/str/{slug}`     |

The code treats them as one thing and fabricates `/str/{username}`:

```
backend/scrapers/ebay_sold.py:263   f".../str/{seller_info['username']}"   (API path)
backend/scrapers/ebay_sold.py:371   f".../str/{seller}"                    (HTML path)
backend/engine/stores.py:48,107     STORE_URL_TEMPLATE + derive_store_url()  (every row)
```

`stores.py` already documents the problem:

- line 13-14 — _"the store URL is **derived** ... **never observed on the page**"_
- line 100-101 — _"`verified` ... does **NOT** mean we confirmed the storefront exists"_

...and then line 114 stamps `provenance: "verified"` anyway. The UI compounds it:
`frontend/components/EbayStoresCard.tsx:67` renders a `derived` chip while
`:79` stamps the same row `Verified` — two contradictory labels on a dead link.

Aggravator: `ebay_sold.py:363-371` scrapes `span.s-item__seller-info-text`, takes
the first whitespace token (which may be a display name rather than a
username), and discards the genuine `/str/{slug}` anchor next to it.

### Runtime

| Observation                              | Verdict                                             |
| ---------------------------------------- | --------------------------------------------------- |
| Command "still running after 2h"         | **Not a bug.** `next start` / `uvicorn` never exit. |
| Root `npm start` -> "Missing script"     | **Defect.** No `start` script exists.               |
| Orphaned `node` pids with port 3000 down | **Defect.** Detached children leak.                 |

## Phase 1 findings (measured)

### Runtime

| Check                  | Result                                                                                                                                                                        |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend start          | healthy — `{"status":"ok"}`, pid bound to 8000                                                                                                                                |
| Frontend start         | healthy — HTTP 200, `next start`, pid bound to 3000                                                                                                                           |
| Orphaned app processes | **none found.** The two `node` pids seen earlier are `shadcn mcp` (agent tooling), not the app. My earlier "process leak" reading was a **mis-attribution and is withdrawn.** |
| Root `npm start`       | fails — root `package.json` has no `start` script                                                                                                                             |

Long-running behaviour is therefore **expected**, not stuck: `next start` and
`uvicorn` do not exit. Only the missing start script is a real defect.

### Store rows

Four products through the real `resolve_stores()` produced **16 store rows**,
and every single one was:

- `url_derived = True`
- `provenance = "verified"`
- URL = `https://www.ebay.co.uk/str/{username}`

So the fabricated-URL path is **confirmed in production output**, not just in
source reading.

### Verification is blocked from this host

| Route                           | Result                                              |
| ------------------------------- | --------------------------------------------------- |
| `www.ebay.co.uk/str/<x>`        | HTTP **200 + CAPTCHA** ("Security measure \| eBay") |
| `www.ebay.co.uk/usr/<x>`        | HTTP **403**                                        |
| `www.ebay.co.uk/sch/` (scraper) | HTTP **403 Forbidden**                              |
| `api.ebay.co.uk`                | **DNS resolution fails**                            |

A deliberate negative control (`/str/zzqx-nonexistent-store-99887766`) returned
the **same** 200 + CAPTCHA as a plausibly-real store. This is exactly the trap
in the brief: a 200 is not proof of identity, and a block is not proof a store
is missing.

**Consequence:** the planned live HTTP verifier is not viable from this host —
it would classify every store as unverified. Decision 1 is superseded below.

## Design decisions

| #   | Decision                                | Resolution                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Live verification: always or on demand? | **SUPERSEDED by Phase 1 evidence.** A live HTTP verifier is not viable from this host — every `/str/` fetch returns a CAPTCHA (proven by negative control), `/usr/` returns 403, and `api.ebay.co.uk` does not resolve. Replaced by: **no network verification dependency.** Authenticity comes from the _provenance of the link_ (observed anchor vs canonical `/usr/` derived from a real username), never from fetching it. |
| 2   | Confirmed 404 -> drop or demote?        | Demote. Row shown with no link, status "Store not found".                                                                                                                                                                                                                                                                                                                                                                      |
| 3   | `url_derived` contract field            | Keep it. Add `url_kind: observed \| seller_profile \| none` alongside (additive only).                                                                                                                                                                                                                                                                                                                                         |
| 4   | Display name when slug != username      | Store name when observed, else username. Carry `username` separately.                                                                                                                                                                                                                                                                                                                                                          |
| 5   | Cache verification?                     | **SUPERSEDED** — there is no verification call to cache. The observed anchor is captured during the listing fetch that already happens.                                                                                                                                                                                                                                                                                        |     |
| 6   | Blast radius                            | Fix once in `engine/stores.py`; all five workflows share `resolve_stores()`.                                                                                                                                                                                                                                                                                                                                                   |

### Fallback ladder

```
Tier 1  observed         real /str/{slug} read from source  -> Verified
Tier 2  seller_profile   /usr/{username}, always exists      -> Partially verified + reason
Tier 3  none             no usable identity                  -> no link, not clickable
```

Never fabricate `/str/{username}`. Never stamp `Verified` on a derived URL.

## Phase 2 outcome

### What changed

| File                            | Change                                                                                                                                                                                                                                                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/engine/stores.py`      | `seller_profile_url()` (`/usr/`) and `store_url_from_observed_slug()` (`/str/`) replace the single conflated builder. `_row()` takes an observed URL, emits `url_kind`, and stamps `unverified` + a reason for profile rows. `build_stores`/`stores_from_items`/`stores_from_top_sellers` thread the observed link through. |
| `backend/scrapers/ebay_sold.py` | HTML path now **reads** the `/str/` anchor eBay rendered instead of discarding it. API path stops fabricating `/str/{username}`. `EbaySoldItem.store_url` added (appended last, so positional construction cannot shift). `top_sellers` carries `store_url`.                                                                |

### REGRESSION-007b — a second, previously invisible bug

`_parse_sold_page` used `lo, hi` at the band gate but never bound them: they
were locals of `_get_sold_via_scrape`, a different scope. Every item therefore
raised `NameError`, and a blanket `except: continue` swallowed it. **The HTML
sold-listing parser always returned zero items**, so store discovery always
fell through to the API path and Tier-1 observed storefronts could never have
been captured even once the anchor was being read.

Fixed by binding `lo, hi = self._resolve_band()` at the top of the method.

### Tests

`tests/test_store_identity.py` (new, 18 tests) covers the two identifiers,
row precedence, the no-fabrication invariant, and the scraper's anchor capture.
It runs fully offline — the fix must not depend on a request.

Four pre-existing tests asserted the defect itself and were updated to the
corrected contract, each with the reason recorded at the site. None were
weakened; several are now strictly stronger:

- `test_stores.py::TestDeriveStoreUrl` — additionally asserts a username is
  never turned into a `/str/` URL
- `test_store_wiring.py::_assert_store_row` — replaced a blanket
  `url.startswith("/str/")` with a two-branch invariant: a `/str/` href may
  only appear on an `observed` row
- `test_rows_built_from_real_names_are_verified` — renamed to
  `..._are_not_claimed_as_confirmed_stores`

**Suite: 1053 passed, 7 skipped** (baseline 1032; +21 new, 0 regressions).

## Phases

| Phase | Work                                                                        | Skill                         | eBay calls | Status  |
| ----- | --------------------------------------------------------------------------- | ----------------------------- | ---------- | ------- |
| 0     | Ticket split / plan doc                                                     | `to-tickets`                  | 0          | done    |
| 1     | Baseline: live runs, store URLs, resolution probe, test counts, orphan pids | `diagnosing-bugs`             | 4 runs     | done    |
| 2     | Store identity: observed -> `/usr/` fallback -> none                        | `domain-modeling`, `grilling` | 0          | done    |
| 3     | Provenance honesty: remove Verified-on-derived contradiction                | `domain-modeling`             | 0          | pending |
| 4     | 12 adversarial store-validation scenarios, red-green-refactor               | `tdd`                         | 0          | pending |
| 5     | Runtime: `start/stop/check.ps1`, root `start` script                        | `diagnosing-bugs`             | 0          | pending |
| 6     | Dashboard UI premium pass on `Scorecard` + `EbayStoresCard`                 | `redesign-existing-projects`  | 0          | done    |
| 7     | Regression + honest verification report                                     | `code-review`                 | 0          | done    |
| 8     | Report with measured before/after                                           | —                             | 0          | done    |

### Dependency map

```
0 -> 1 -> 2 -> 3 -> 6 -> 7 -> 8
          2 -> 4 -.
          4 ----'   (4 and 5 are independent, either order)
          5 --------
```

Phase 3 must precede Phase 6: polishing the UI before the labels are true means
beautifying a lie.

## Report

Populated with observed values only. Anything not measured is labelled
**not verified**.

| Area                        | Before                                                                          | After                                                                                                                    | Evidence                          |
| --------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| Store validity              | all 16 baseline rows built `/str/{username}` (derived) while stamped `verified` | **0 fabricated `/str/` URLs across 12 live rows**; every link is either an observed anchor or canonical `/usr/`          | live run, Phase 7                 |
| Fabricated store prevention | not tested                                                                      | 35 adversarial scenarios; **2 real holes found and closed** (off-eBay host accepted; `sold_count='x'` crashed discovery) | `tests/test_store_adversarial.py` |
| Block vs rows               | block read `verified` while every row read `unverified`                         | block takes the weakest row; carries `confirmed_storefronts`                                                             | Phase 7 live run                  |
| Normal analysis             | `resolve_stores()` — derived `/str/`                                            | same path, honest links                                                                                                  | source trace + live               |
| Deep Search                 | `resolve_stores()` — derived `/str/`                                            | same path, honest links                                                                                                  | source trace + live               |
| All five workflows          | each called `resolve_stores()`                                                  | unchanged — **one fix, five paths**                                                                                      | source trace                      |
| Server startup              | root `npm start` failed (no script); no stop/check                              | `npm start\|stop\|check`; verified stop→start→check from cold                                                            | Phase 5 run                       |
| Dashboard UI                | uniform border+fill tiles; verdict buried last                                  | hero + decision-first hierarchy; new radius/shadow tokens                                                                | Phase 6; CSS bundle verified      |
| Regression risk             | 1032 passed, 7 skipped                                                          | **1092 passed, 7 skipped** (+60), vitest 47, typecheck clean                                                             | pre-commit hook                   |

### eBay calls

**1 attempted of 20 budgeted.** The single Browse API attempt never left the
host (`api.ebay.co.uk` does not resolve from this network). The 12-row live
check resolved through the HTML path, which does not bill an API call. HTML
request counts are **not instrumented** and are not claimed.

### Not verified — and why

| Claim                                    | Status                            | Reason                                                                                                                                                                                                                                                                   |
| ---------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Per-link liveness of `/str/` and `/usr/` | **not verified**                  | eBay serves a CAPTCHA for `/str/` and 403 for `/usr/` from this host. A deliberate negative control returned the same 200+CAPTCHA as a plausible store, so a 200 proves nothing. Only the project's Playwright+stealth path could check this, and that was out of scope. |
| Pixel-level UI appearance                | **not verified**                  | No browser or screenshot tooling available. Verified structurally instead: typecheck, build, emitted CSS tokens and utilities, page status codes.                                                                                                                        |
| Before/after count of dead store links   | **not measurable from this host** | Same CAPTCHA/403 constraint. The fix removes the fabrication entirely, so every emitted link is now either an observed eBay anchor or eBay's canonical form — but whether each destination resolves was not observed.                                                    |

### Remaining limitations

- **Option A was chosen**, so unconfirmed storefronts link to `/usr/`
  (the seller's account page), clearly labelled "Seller profile". That is a
  real page but it is not a shop. If you later want shopfronts, the Playwright
  path in `scrapers/base.py` is the route.
- `_search_scrape` in `backend/scrapers/ebay.py` still never populates
  `seller`, so the plain-search fallback contributes no stores. Pre-existing,
  not touched — discovery reaches stores through the sold query.
- `resolve_stores()` keeps its 6-parameter signature with a `provenance`
  out-param. `codebase-design` vocabulary was used to shape the new code
  (return results, small interface, one seam); the signature itself was left
  alone deliberately, to keep the diff inside §7 scope control.
- The GitHub token in the shell history and in this session should be
  rotated.

**eBay API calls used: 1 attempted / 20 budgeted**
