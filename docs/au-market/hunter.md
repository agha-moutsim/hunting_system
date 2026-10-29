# AU Category Hunter - Phase E4

Phase E4 unlocks Category Hunter for `EBAY_AU` in AUD. Scan and lookup follow
`analyze_ready`, so AU runs with its sourced card and bench while the
standalone fee calculator stays locked until Phase E5.

## The gate

`api/hunter.py` uses `_require_ready_market()`, which calls
`marketplaces.analyze_ready()`:

- `EBAY_GB` and `EBAY_AU` pass;
- US, DE and CA are refused with `422` and a sentence naming the missing
  piece.

`POST /api/hunter/scan` and `POST /api/hunter/lookup` now return
`marketplace`, `currency` and `currency_symbol`.

## Market propagation

- Scan uses the market's own site, marketplace id, delivery country and
  price currency. UK keeps the persisted active range; AU uses its market band.
- Demand checks use `EbaySoldScraper(marketplace)` and the market's demand
  floors; stores are resolved with the market host.
- Supplier lookup already received `marketplace`; direct CJ/AliExpress scrapers
  now receive it too, so AU uses the AU bench and AU currency.
- Profit calculation uses the market's fee table, `ebay_au` source token,
  `DecisionEngine(..., marketplace=...)`, and the AU demand floors.

## UI

- `frontend/app/hunter/page.tsx` reads `useMarketplace()`.
- AU uses its fixed market band; the UK keeps the user-adjustable range.
- A market without `analyze_ready` shows a lock notice and disables scan and
  lookup.
- Money values use `formatMoney(..., currency)`.
- Switching market clears the previous scan and report.

## Pins

- `tests/test_au_hunter.py` - AU scan and lookup unlocked and labelled AUD,
  US refusal, and market propagation.
- `tests/test_hunter_regressions.py`, `tests/test_filters_api.py` - UK scan,
  range resolution and lookup behaviour unchanged.
  PY
