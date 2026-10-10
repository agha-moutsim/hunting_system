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

## Design decisions

| #   | Decision                                | Resolution                                                                                                                                                                       |
| --- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Live verification: always or on demand? | Always, bounded at 12 URLs/run, 1.5s timeout, 1s cooldown, 15-min in-memory cache. Fail-open: budget/timeout exhausted -> `verification_unavailable`, never silently "verified". |
| 2   | Confirmed 404 -> drop or demote?        | Demote. Row shown with no link, status "Store not found".                                                                                                                        |
| 3   | `url_derived` contract field            | Keep it. Add `url_kind: observed \| seller_profile \| none` alongside (additive only).                                                                                           |
| 4   | Display name when slug != username      | Store name when observed, else username. Carry `username` separately.                                                                                                            |
| 5   | Cache verification?                     | Yes. In-memory, TTL 15 min, keyed by canonical URL. No schema change.                                                                                                            |
| 6   | Blast radius                            | Fix once in `engine/stores.py`; all five workflows share `resolve_stores()`.                                                                                                     |

### Fallback ladder

```
Tier 1  observed         real /str/{slug} read from source  -> Verified
Tier 2  seller_profile   /usr/{username}, always exists      -> Partially verified + reason
Tier 3  none             no usable identity                  -> no link, not clickable
```

Never fabricate `/str/{username}`. Never stamp `Verified` on a derived URL.

## Phases

| Phase | Work                                                                                     | Skill                         | eBay calls | Status  |
| ----- | ---------------------------------------------------------------------------------------- | ----------------------------- | ---------- | ------- |
| 0     | Ticket split / plan doc                                                                  | `to-tickets`                  | 0          | done    |
| 1     | Baseline: live runs, store URLs, resolution check, screenshots, test counts, orphan pids | `diagnosing-bugs`             | 8          | pending |
| 2     | Store identity: observed -> `/usr/` fallback -> none                                     | `domain-modeling`, `grilling` | 0          | pending |
| 3     | Provenance honesty: remove Verified-on-derived contradiction                             | `domain-modeling`             | 0          | pending |
| 4     | 12 adversarial store-validation scenarios, red-green-refactor                            | `tdd`                         | 0          | pending |
| 5     | Runtime: `start/stop/check.ps1`, process-tree kill, root `start` script                  | `diagnosing-bugs`             | 0          | pending |
| 6     | Dashboard UI premium pass on `Scorecard` + `EbayStoresCard`                              | `redesign-existing-projects`  | 0          | pending |
| 7     | Regression + live verification                                                           | `code-review`                 | 12         | pending |
| 8     | Report with measured before/after                                                        | —                             | 0          | pending |

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

Populated after Phase 7 with observed values only. Anything not measured is
labelled **not verified**.

| Area                        | Before            | After | Evidence |
| --------------------------- | ----------------- | ----- | -------- |
| Store validity              | _pending Phase 1_ |       |          |
| Fabricated store prevention | _pending Phase 4_ |       |          |
| Normal analysis             | _pending Phase 1_ |       |          |
| Deep Search                 | _pending Phase 1_ |       |          |
| Server startup              | _pending Phase 1_ |       |          |
| Dashboard UI                | _pending Phase 1_ |       |          |
| Regression risk             | _pending Phase 1_ |       |          |

**eBay calls used: 0 / 20**
