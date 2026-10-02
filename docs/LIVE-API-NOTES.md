# Live API capture notes — what eBay and SerpApi actually return

Recorded 2026-10-03 against the production endpoints, using
`tests/capture_fixtures.py`. Everything here was observed, not assumed. The
committed fixtures under `tests/fixtures/` are the payloads these notes
describe.

Why this file exists: every earlier fixture in this repo was hand-written, and
hand-written JSON cannot tell you when a vendor changes a field. Three real
defects in this codebase were invisible to the suite and obvious here.

---

## eBay Browse API — `item_summary/search`

Endpoint: `GET https://api.ebay.com/buy/browse/v1/item_summary/search`
Auth: OAuth2 client-credentials token in the `Authorization` header. Never
logged, never stored, never in a fixture.

### Fields the code depends on

| Field                             | Shape observed                 | Note                                                                       |
| --------------------------------- | ------------------------------ | -------------------------------------------------------------------------- |
| `itemSummaries[].price`           | **object** `{currency, value}` | Not a number. Code written against a float crashes on the first live call. |
| `itemSummaries[].itemWebUrl`      | string                         | The canonical listing URL.                                                 |
| `itemSummaries[].seller`          | **object** `{username, ...}`   | `seller` is nested, not a flat string.                                     |
| `itemSummaries[].condition`       | string, eBay's own label       | See the vocabulary problem below.                                          |
| `itemSummaries[].itemLocation`    | object `{country, ...}`        |                                                                            |
| `itemSummaries[].shippingOptions` | array                          | Only present sometimes; absent must stay unknown.                          |
| `itemSummaries[].thumbnailImages` | array of `{imageUrl, ...}`     |                                                                            |

### Condition vocabulary actually returned

Captured for `q=greenhouse 6ft`:

```
New other (see details)
Certified - Refurbished
Certified - Refurbished
New
```

**This is the finding that mattered.** `New other (see details)` and
`New condition` are genuinely New. The gate's whitelist was exact-match after
stripping punctuation, so `newotherseedetails` matched nothing and both were
rejected — a silent false negative that removed real New listings from a
New-only product. Fixed in `engine/condition_gate.py`: the not-New pass runs
first and wins on a marker anywhere in the label, then a leading `new`
counts as New. `Newly refurbished` still loses to its refurb marker.

`New - Open Box` is **unresolved and needs a product decision** — it is a new
item in an opened box, and `openbox` is in the not-New list. See
`tests/test_condition_gate_real_labels.py`.

### Price band

`filter=price:[5..35],priceCurrency:GBP`. The four captured listings cost
£156.70–£465.70, so a £5–£35 band correctly discards every one of them. Worth
recording because it looks like a bug in the UI until you see the prices.

### Sold listings

`sold_count_30d` is **the number of in-band New listings a
`sort=-dateSold` search returned** — capped at `limit=50`. It is a
search-page count, not a verified 30-day sales total.

This is now stated in the data itself: `data_source` is set to
`ebay_browse_sold_search: count of in-band New sold listings the search
returned; a search-page count, not a sales total`. Found by the live smoke
test, which caught `data_source = None` on a perfectly real figure. The
label deliberately avoids the words "verified" and "exact" so a renderer
string-matching the source cannot light a green badge on it.

`sold_count_7d` is always `None` from this endpoint — eBay exposes no sold
dates. A real 7-day figure needs either the browser extension's purchase
history or the watchlist monitor sampling the same query twice.

Live check, `cordless drill`: `sold_count_30d=50`, `avg_sold_price=20.76`,
4 real sellers recovered from the same response.

---

## SerpApi — `google_shopping`

Endpoint: `GET https://serpapi.com/search.json?engine=google_shopping`

### Three stages, because one call is not enough

1. Generic `google_shopping` → `shopping_results[]`. Google's own links
   (`product_link`) carry **no merchant host**, so the domain match in
   `_slug_for` never fires and the displayed `source` is the fallback.
2. `site:` pass per missing supplier (drop-shippers first — Google Shopping
   ranks high-street retailers on its own).
3. One `google_immersive_product` call per kept row, using
   `immersive_product_page_token` from stage 1, to get the real store URL,
   price and stock.

### Fields the code depends on

| Field                                             | Shape observed            | Note                                                          |
| ------------------------------------------------- | ------------------------- | ------------------------------------------------------------- |
| `shopping_results[].extracted_price`              | float                     | The usable price.                                             |
| `shopping_results[].price`                        | string, `"£49.99"`        | Display only. Parsing this is a fallback.                     |
| `shopping_results[].source`                       | string, e.g. `GardenSite` | Displayed seller. **Often absent.**                           |
| `shopping_results[].product_link`                 | Google redirect URL       | Not the merchant URL.                                         |
| `shopping_results[].immersive_product_page_token` | long opaque string        | **Pagination cursor, not a credential.** Required by stage 3. |

Two traps worth keeping written down:

- `supplier_type` on a built row is `classify_source()`'s answer to _what kind
  of seller is this_ — `dropshipper` / `wholesaler` / `retailer` / `unknown`.
  It is **not** a supplier identity. The live smoke test initially asserted an
  approved slug against it and failed on correct code. C12 membership is
  carried by `source`, which `_row_for` fills from the approved supplier's own
  configured label.
- A blanket "delete any key containing `token`" scrubber deletes
  `immersive_product_page_token` — the exact field stage 3 needs. The capture
  script now keeps that field explicitly and a test asserts it survives.

### Reliability

SerpApi timed out (20s) on one of five live smoke runs. `discover()` fails
closed on a timeout and returns fewer rows rather than raising, which is the
correct behaviour — but it means a supplier row can be absent for reasons
that have nothing to do with the product. That is why supplier absence is
reported as a status with a reason, never as "no suppliers exist".

---

## What this changed, in one place

| Defect                                            | Found by                | Fix                                       |
| ------------------------------------------------- | ----------------------- | ----------------------------------------- |
| Postage dropped from every verdict                | Reading `decisions.py`  | Shipping threaded into `calculate_profit` |
| `£0.004` postage moved profit but printed `£0.00` | Hypothesis              | Known-ness decided on the displayed value |
| Real New labels rejected                          | Real eBay fixture       | Not-New first, then a `new` prefix        |
| Sold count could not name its source              | Live smoke test         | `data_source` stamped on both paths       |
| Stale trend series answered as current            | Reading `compute_trend` | Staleness window using the unused `now`   |
| Fixture scrubber deleted the field under test     | Real SerpApi fixture    | Explicit keep-list + a guard test         |

## Re-capturing

```powershell
$env:SERPAPI_KEY = (Select-String -Path .env -Pattern "^SERPAPI_KEY=").Line -replace "^SERPAPI_KEY=",""
python tests\capture_fixtures.py
python -m pytest tests/test_real_payload_fixtures.py -q
```

Re-capture when a vendor changes a shape. The guard tests will tell you if the
scrubber has quietly removed something the parsers need.
