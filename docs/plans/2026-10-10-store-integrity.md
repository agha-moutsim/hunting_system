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

## Phases

| Phase | Work                                                                        | Skill                         | eBay calls | Status  |
| ----- | --------------------------------------------------------------------------- | ----------------------------- | ---------- | ------- |
| 0     | Ticket split / plan doc                                                     | `to-tickets`                  | 0          | done    |
| 1     | Baseline: live runs, store URLs, resolution probe, test counts, orphan pids | `diagnosing-bugs`             | 4 runs     | done    |
| 2     | Store identity: observed -> `/usr/` fallback -> none                        | `domain-modeling`, `grilling` | 0          | pending |
| 3     | Provenance honesty: remove Verified-on-derived contradiction                | `domain-modeling`             | 0          | pending |
| 4     | 12 adversarial store-validation scenarios, red-green-refactor               | `tdd`                         | 0          | pending |
| 5     | Runtime: `start/stop/check.ps1`, root `start` script                        | `diagnosing-bugs`             | 0          | pending |
| 6     | Dashboard UI premium pass on `Scorecard` + `EbayStoresCard`                 | `redesign-existing-projects`  | 0          | pending |
| 7     | Regression + honest verification report                                     | `code-review`                 | 0          | pending |
| 8     | Report with measured before/after                                           | —                             | 0          | pending |

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

| Area                        | Before                                                                                                                                                       | After | Evidence                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- | ---------------------------------------------- |
| Store validity              | **not verified** — all 16 baseline rows built `/str/{username}` (derived), but eBay blocks `/str/` with a CAPTCHA so no row could be confirmed dead or alive |       | `backend/engine/stores.py:48,107`; Phase 1 run |
| Fabricated store prevention | confirmed as a source-level defect (every row `url_derived=True` + `provenance="verified"`)                                                                  |       | Phase 1 run output                             |
| Normal analysis             | stores produced through the same `resolve_stores()` path                                                                                                     |       | source trace                                   |
| Deep Search                 | stores produced through the same `resolve_stores()` path                                                                                                     |       | source trace                                   |
| Server startup              | backend + frontend both start and serve 200; root `npm start` fails (no script)                                                                              |       | Phase 1 process + health capture               |
| Dashboard UI                | 9/9 pages 200; byte sizes recorded; no browser available for pixel screenshots                                                                               |       | Phase 1 capture                                |
| Regression risk             | baseline **1032 passed, 7 skipped**                                                                                                                          |       | pre-commit hook                                |

**eBay API calls used: 1 attempted / 20 budgeted.** The single Browse API
attempt never left the host (DNS failure for `api.ebay.co.uk`). The 4 product
runs resolved via the HTML path, which does not bill an API call. Request counts
for the HTML path are **not instrumented** and are therefore not claimed.

**Known limitation:** the brief asks for a before/after count of dead store
links. That number **cannot be measured from this host** — eBay serves a
CAPTCHA for `/str/` and 403 for `/usr/`, proven with a negative control. The
fix removes the fabrication entirely, which makes every emitted link either an
observed eBay anchor or eBay's canonical `/usr/` form; per-link liveness is
reported as **not verified**.
