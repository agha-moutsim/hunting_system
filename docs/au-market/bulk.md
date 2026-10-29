# AU Bulk - Phase E3

Phase E3 unlocks Bulk for `EBAY_AU` in AUD. Bulk runs `deep_search_fast()` for
many queries at once, so it follows the same `analyze_ready` switch as Analyze
and Deep Search. The standalone fee calculator remains unlocked in Phase E5.

## The gate

`api/bulk.py::_require_ready_market()` calls `marketplaces.analyze_ready()`:

- `EBAY_GB` and `EBAY_AU` pass;
- US, DE and CA are refused with `422` and a sentence naming the missing
  piece ("No USD fee table is registered...").

The old "UK-only" refusal is gone: Bulk can price a resale wherever Analyze
can.

`POST /api/bulk` now returns `marketplace`, `currency` and
`currency_symbol` beside the results. Each result already carries its own market
and currency (Phase E2), so a mixed or stale run cannot relabel money.

## Market propagation

- UK keeps the historical one-argument `deep_search_fast(query)` call.
- A non-UK run passes `marketplace=market["id"]`, so the fast path follows
  `EBAY_AU`: the AUD band and 15/10 demand floors, the AU sold site and
  currency, and the AU supplier bench.
- Each query is still processed sequentially; an exception on one query is
  reported in `errors` and does not stop the rest.

## Currency

Bulk inherits the fast-path currency boundary from Phase E2:

- AliExpress AUD rows pass through unchanged; CJ's USD `sellPrice` is tagged
  `USD` and excluded from the AUD comparison with a sentence rather than
  converted.
- An unstated currency is accepted only for GBP; on AU an untagged row is not
  assumed to be AUD.
- Supplier rows keep their own `currency`; the UI formats each row in its own
  currency.

## UI

- `frontend/app/bulk/page.tsx` reads `useMarketplace()`.
- A market without `analyze_ready` shows a lock notice and disables the form.
- Every money value uses `formatMoney(..., currency)`.
- Switching market clears the previous result, so a GBP run is never relabelled
  as AUD.

## Pins

- `tests/test_au_bulk.py` - AU route unlocked and labelled AUD, US refusal,
  and UK/AU market propagation.
- `tests/test_au_deep_search.py` - the fast-path currency boundary Bulk
  reuses.
  PY
