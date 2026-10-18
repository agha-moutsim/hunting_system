# System Architecture

Architecture of the ten new features. Existing components appear only where a new feature plugs
into them.

---

## 1. Layers

```
+-----------------------------------------------------------------------+
|  EXTENSION (Chrome MV3, plain JS)                                     |
|  content.js   item-page detector + capture queue      [NEW]           |
|  background.js  dedupe, badge, retry, POST            [CHANGED]       |
|  popup.*      status, quiet mode, seed queue          [CHANGED]       |
+----------------------------+------------------------------------------+
                             | POST /api/extension/sold-history
                             | POST /api/extension/capture-queue   [NEW]
                             v
+-----------------------------------------------------------------------+
|  API (FastAPI)   read routes never fetch                              |
|  extension.py   capture intake + parse                [CHANGED]       |
|  fees.py        fee model + reverse mode              [NEW]           |
|  alerts.py      alert inbox, mark read                [NEW]           |
|  titles.py      token frequency for a query           [NEW]           |
|  sellers.py     seller footprint                      [NEW]           |
|  sales.py       own-sales entry + P&L                 [NEW]           |
|  observations.py listing age + churn                  [NEW]           |
+----------------------------+------------------------------------------+
                             v
+-----------------------------------------------------------------------+
|  ENGINE / SERVICES                                                    |
|  engine/fees.py       THE fee implementation, one only [NEW]          |
|  engine/titles.py     n-gram frequency from corpus     [NEW]          |
|  engine/listing_age.py age from creation date + churn  [NEW]          |
|  engine/sellers.py    footprint from observations      [NEW]          |
|  scrapers/browse_fields.py  one extractor for the rich  [NEW]         |
|                             Browse fields                            |
|  scrapers/ebay_deals.py     existing Browse client, token reuse       |
|  hunter/*             existing discovery + monitors                   |
+----------------------------+------------------------------------------+
                             v
+-----------------------------------------------------------------------+
|  STORAGE (SQLite)                                                     |
|  purchase_captures      existing, becomes append + latest-read [CHANGED]|
|  listing_observations   NEW - the accumulating supply table           |
|  price_alerts / saved_searches / search_results   existing, now fed   |
|  sales / monthly_stats  existing, now fed                             |
|  demand_data            existing, provenance columns added    [CHANGED]|
+-----------------------------------------------------------------------+
                             ^
+----------------------------+------------------------------------------+
|  FRONTEND (Next.js)                                                   |
|  /alerts  /titles  /sellers  /sales  /sources  ...  [NEW]             |
|  verified-vs-search presentation in Analyze / History [CHANGED]       |
+-----------------------------------------------------------------------+
```

---

## 2. The two accumulation tables

Everything downstream depends on these. They are the reason collection is Phase A and B.

### `listing_observations` [NEW]

One row per (listing, observation time). Never upserted, never overwritten - the history _is_
the product.

```
id                    INTEGER PK
listing_id            TEXT     indexed       eBay legacyItemId
marketplace           TEXT     default 'EBAY_GB'
observed_at           DATETIME indexed       naive UTC
title                 TEXT
price_value           REAL     nullable       NULL = not read
price_currency        TEXT
condition             TEXT
condition_id          INTEGER
item_creation_date    DATETIME nullable       from Browse
item_origin_date      DATETIME nullable
seller_username       TEXT
seller_feedback_score INTEGER  nullable
seller_feedback_pct   REAL     nullable
seller_account_type   TEXT     nullable       BUSINESS | INDIVIDUAL
seller_region         TEXT     nullable       itemLocation country + postal prefix
postage_cost          REAL     nullable
postage_currency      TEXT
buying_options        TEXT     nullable
top_rated             BOOLEAN  nullable
priority_listing      BOOLEAN  nullable
query                 TEXT     nullable       the query that surfaced it, if any
source                TEXT                    browse_search | browse_by_id | deals | extension
```

What it enables:

- **Phase G** - age at first sight (`item_creation_date`), and churn by comparing consecutive
  observations of the same `listing_id`.
- **Phase H** - seller footprint aggregated from observations.
- **Postage-in-margin** - real postage cost per listing.
- **Phase I feedback** - the observation history is what the C14 thresholds can be replayed against.

### `purchase_captures` [CHANGED]

Today: upsert by `item_id`, latest wins. That is correct for "what are the sold numbers now" and
wrong for a trend, because each capture destroys the previous one.

Change to **append, read latest**: keep inserting rows, and have readers select the newest row per
`item_id`. This preserves the current semantics for every existing caller while making a sold
trend possible. The existing unique constraint on `item_id` (if relied upon) is replaced by an
index; the read path gains an `ORDER BY captured_at DESC LIMIT 1` per item.

Existing columns stay as they are: `item_id`, `url`, `sold_7d`, `sold_30d`, `sales_json`,
`captured_at`, `source`.

---

## 3. Data flows

### Flow 1 - passive capture (Phase A)

```
user browses an eBay item page
  -> content.js detects /itm/<id>
  -> asks background.js "seen recently?"
       yes (inside dedupe window) -> stop, no request
       no  -> background.js fetches purchaseHistory in the user's session
           -> POST /api/extension/sold-history
           -> backend parses -> INSERT purchase_captures row
           -> replies {stored, sold_7d, sold_30d}
  -> background.js increments today's count and sets the badge
```

Rate is bounded by the user's browsing, which is the point (see constraints section 4).

### Flow 2 - rich field persistence (Phase B)

```
Analyze / Hunter / Deals run
  -> Browse API call (already made today)
  -> scrapers/browse_fields.py extracts creation date, seller, region, postage
  -> INSERT listing_observations row
```

**No extra API calls.** The same response, with fields kept instead of discarded.

### Flow 3 - verified-first presentation (Phase C)

```
GET product
  -> verified sold data?  (a purchase_captures row for this listing)
       yes -> primary figure: sold count, stamped VERIFIED, with capture date
       no  -> secondary figure: Browse search count, stamped as a search count
              and explicitly NOT a sales total
  -> each field emitted with {value, origin, observed_at}
  -> UI renders the value and its origin together, or "not measured"
```

### Flow 4 - fee calculation (Phase D)

```
inputs: sale price, postage charged, postage paid, category, promoted %, VAT registered?,
        seller type (business|private), supplier cost
  -> engine/fees.py  ->  final value fee, fixed fee, promoted fee, net, break-even
  -> reverse mode: solve sale price for a target margin
```

Single implementation. The pipeline verdict and the calculator call the same function.

---

## 4. Schema changes summary

| Object                                                                       | Change                                                                                                    |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `listing_observations`                                                       | NEW table                                                                                                 |
| `purchase_captures`                                                          | append instead of upsert; readers take latest per item                                                    |
| `demand_data`                                                                | add `sold_source` / capture-reference columns so a verified figure is distinguishable from a search count |
| `supplier_matches`                                                           | unchanged (already carries provenance)                                                                    |
| `price_alerts`, `saved_searches`, `search_results`, `sales`, `monthly_stats` | no schema change - they need writers, not columns                                                         |
| `products`                                                                   | keep `condition`, `seller`, `category`; no change needed for A-F                                          |

Migration follows the existing pattern: an idempotent `ensure_listing_observations_table()` and
`ensure_observation_columns()` called on import from `backend/db/database.py`, with the new table
created at the **end** of `backend/db/models.py` after its model class is defined - the same
ordering that `ensure_deal_items_table()` requires.

---

## 5. New API surface

| Method | Route                                   | Purpose                             | Honesty contract                                              |
| ------ | --------------------------------------- | ----------------------------------- | ------------------------------------------------------------- |
| POST   | `/api/extension/sold-history`           | existing capture intake             | returns `stored`, and a reason when it refuses                |
| GET    | `/api/extension/sold-history/{item_id}` | existing read-back                  | unchanged                                                     |
| GET    | `/api/extension/status`                 | badge: today's captures, quiet mode | counts only, no estimates                                     |
| POST   | `/api/extension/capture-queue`          | seed a small explicit list          | human-paced, rejects unbounded lists                          |
| POST   | `/api/fees/calculate`                   | fees, break-even, reverse mode      | pure arithmetic, echoes the inputs and the fee table version  |
| GET    | `/api/alerts`                           | alert inbox                         | each alert names the two prices it compared                   |
| POST   | `/api/alerts/{id}/read`                 | mark read                           | -                                                             |
| GET    | `/api/titles?q=`                        | token frequency                     | returns counts over N listings and states N; no volume claims |
| GET    | `/api/sellers/{username}`               | footprint                           | active-listing-derived only; no revenue field exists          |
| GET    | `/api/sales` / POST                     | own sales                           | user-entered or imported; labelled as user-declared           |
| GET    | `/api/sales/summary`                    | P&L                                 | arithmetic over stored sales                                  |
| GET    | `/api/observations/{listing_id}`        | age + churn                         | "no longer listed", never "sold"                              |

---

## 6. Scheduled jobs

Reuse the existing scheduled pattern (the deals refresh and the demand monitor already run this
way, registered with Windows Task Scheduler).

| Job               | Cadence  | Browse cost                                                                  |
| ----------------- | -------- | ---------------------------------------------------------------------------- |
| Deals refresh     | hourly   | ~108 calls (unchanged)                                                       |
| Demand monitor    | existing | existing                                                                     |
| Alert evaluation  | hourly   | 0 - reads stored observations                                                |
| Saved-search runs | daily    | must be budgeted before enabling                                             |
| Observation sweep | none     | observations are recorded as a side effect of runs the user already triggers |

Alert evaluation and reads cost nothing. The only new Browse consumer is saved-search runs, which
must be added last and budgeted explicitly against the 5,000/day ceiling.

---

## 7. Provenance flow

```
Browse response
  -> browse_fields.py extracts value + records that Browse was the source
  -> listing_observations.source = 'browse_search'
  -> API serialises {value, origin, observed_at}
  -> frontend fieldProvenance maps origin -> Badge tone
  -> Metric(label, prov, value) renders badge beside the number
```

A purchase-history capture travels the same path with `source = 'extension'` and renders as
`VERIFIED`. The distinguishing rule for the whole system: **the origin of a number is part of the
number**, and any surface that shows one without the other is a defect.
