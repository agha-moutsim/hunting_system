# AU Deep Search - Phase E2

Phase E2 unlocks Deep Search for `EBAY_AU` in AUD. It uses the same
`analyze_ready` switch as Analyze, so the standalone fee calculator remains
unlocked in Phase E5.

## The gate

`api/deep_search.py::_require_ready_market()` calls
`marketplaces.analyze_ready()`:

- `EBAY_GB` and `EBAY_AU` pass;
- US, DE and CA are refused with `422` and a sentence naming the missing
  piece ("No USD fee table is registered...").
- The old "UK-only" refusal is gone: Deep Search can price a resale wherever
  Analyze can.

`POST /api/deep-search` now returns `marketplace`, `currency` and
`currency_symbol` beside the job id. The job record carries the market, and
every poll payload (running, failed, timed out, finished) is labelled with it.
UK jobs keep the historical three-argument `deep_search_product()` call; only a
non-UK job passes its market id.

## eBay sold search

`EbaySoldScraper(marketplace="EBAY_AU")` follows one market record:

- site: `https://www.ebay.com.au`;
- Browse API header: `X-EBAY-C-MARKETPLACE-ID: EBAY_AU`;
- filters: `deliveryCountry:AU`, `priceCurrency:AUD`;
- default band: `A$0.99-A$50.00` (UK keeps the active user range);
- store links and seller profiles are built on the same host, so a UK
  storefront cannot be mistaken for an observed AU one.

The zero-argument constructor remains the UK path.

## Filters, prompt and parsing

- UK uses `utils.filters.load_filters()`.
- AU uses `marketplaces.market_filter_defaults()` + `engine.price_gate.clamp_band()`,
  giving the AUD band and the 15/10 demand floors. A bad AU band falls back to
  the AUD band, never to GBP 5..35.
- `_system_prompt(market)` returns the UK prompt byte-for-byte for
  `EBAY_GB`; for AU it replaces the country, currency, symbol and range
  template. The model is asked for `AUD (A$)`.
- `_llm_price_range_in_band()` reads the market symbol and band. For a
  non-GBP market an unlabelled range is discarded rather than read as GBP.
- `_extract_price()` requires JSON-LD `priceCurrency: AUD` for AU; the visible
  fallback accepts `A$` only. A page that states no usable AUD price is
  dropped.

## Supplier bench and currency

Web queries and SerpApi discovery are scoped to the market bench:

- AU: AliExpress + CJ only. B&Q, Toolstation and Joybuy never get a query.
- UK: its historical five suppliers.

Supplier rows carry their own `currency`. A row stating a currency other than
the market's is excluded with a sentence such as:

> 1 supplier row(s) priced in USD were excluded from the AUD comparison - no
> currency conversion is applied.

An unstated currency is accepted only for GBP (the historical UK scrapers
converted without tagging). On AU an untagged row is not assumed to be AUD.

Fast-path scrapers receive `marketplace="EBAY_AU"` only for non-UK runs; the UK
keeps its zero-argument constructors. The fast path also submits only the
bench's scraper tasks, so a narrower bench cannot call an unlisted source.

## Verdict

`_calculate_profit_and_verdict()` now takes `filters` and `marketplace`:

- evidence and demand carry the market currency;
- `DecisionEngine(..., marketplace=market["id"])` uses the AU card and AU
  floors;
- the evidence `source` is `ebay_uk` for the UK and `ebay_au` for AU;
- supplier ranking receives the market country code.

`DeepSearchResult` gained three appended fields - `marketplace`, `currency`,
`currency_symbol` - so positional construction elsewhere cannot shift.

## UI

- `frontend/app/deep-search/page.tsx` reads `useMarketplace()`.
- The band badge shows the market's own band; the AU `RangeControl` is hidden
  because its band is fixed in the market record.
- A market without `analyze_ready` shows a lock notice and disables the form.
- Every money value uses `formatMoney(..., currency)`. Supplier rows use their
  own `currency`; the sold-price chart takes a `currency` prop.
- Switching market clears the previous result, so a GBP run is never relabelled
  as AUD.

## Pins

- `tests/test_au_deep_search.py` - AU sold scraper defaults and API filters,
  storefront host, market prompt, bench-scoped queries, AUD fast path,
  foreign-currency exclusion, AU verdict floors, full-path wiring, API job
  labels, and the remaining US refusal.
- `tests/test_markets.py` - the refusal now says "not enabled" and names the
  missing USD card.
- `tests/test_deep_search_jobs.py`, `tests/test_provenance.py`,
  `tests/test_store_wiring.py` - UK call shapes and job lifecycle unchanged.
