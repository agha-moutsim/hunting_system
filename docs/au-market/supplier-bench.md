# AU supplier bench - Phase D

Phase D makes the supplier bench a **market property**, not a UK constant. The
bench is the active source list a market may use; it is deliberately smaller
than `backend/suppliers.json`, which is the historical catalog.

## The two benches

| Market    | Active bench                                          | Why                                                                                                   |
| --------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `EBAY_GB` | AliExpress, CJ Dropshipping, B&Q, Toolstation, Joybuy | The existing UK retail/dropship bench. Amazon UK and GoDropship stay disabled in the catalog.         |
| `EBAY_AU` | AliExpress, CJ Dropshipping                           | Dropship-only. B&Q, Toolstation and Joybuy are UK retailers and are not carried into an AUD analysis. |

The source of truth is `supplier_bench` in `config.MARKETPLACES`; the only
reader is `marketplaces.supplier_bench()`. A market with no bench is empty,
never a quiet fallback to the UK list.

`GET /api/marketplaces` exposes the bench as `supplier_bench` so the UI can
show which sources a market will use. It does not mean the market is unlocked.

## What is wired

- **SerpApi discovery** (`scrapers/serpapi_discovery.py`): `discover(query,
marketplace=...)` filters results to the bench and searches Google Shopping
  in that market (`Australia` / `au` for AU). An AU query cannot return a B&Q,
  Toolstation or Joybuy row: the slug is rejected before a row is built.
- **Category Hunter lookup** (`hunter/supplier_lookup.py`): the lookup takes a
  `marketplace`; the AU path skips Joybuy entirely and passes AU to discovery.
  The route still refuses AU until Phase E4, so this is preparation, not an
  unlock.
- **Analyze supplier step** (`analysis_pipeline.search_all_suppliers`): takes a
  `marketplace` and only instantiates the bench's scrapers. The default is the
  UK, so existing behaviour is unchanged.
- **Analyze gate** (`api/analyze.py`): checks `analyze_ready`, which requires
  the market's own flag, a registered fee card and a non-empty bench. AU's
  Analyze is unlocked in Phase E1; the standalone fee calculator remains
  gated by `fee_calculator_ready` until Phase E5.

## Currency is handled per source

The bench decides **which sources** may answer. It does not convert a supplier
price into AUD, and no row is converted across currencies.

- `scrapers/aliexpress_api.py` defaults to `GB` / `GBP` / `en_GB` for the UK;
  an AU scraper passes `AU` / `AUD` / `en_AU` per call. AUD rows pass through
  unchanged; a row stating another currency is skipped.
- `scrapers/cjdropshipping.py` reads CJ's `sellPrice` as USD. The UK path keeps
  its historical fixed `0.79` conversion; a non-GBP market tags the row
  `currency="USD"` and the pipeline excludes it from the AUD comparison with a
  sentence. CJ's browser fallback is disabled for non-GBP because the page does
  not state its currency.
- The AliExpress browser fallback is likewise disabled for non-GBP.

Phase E1 therefore enables AU Analyze with native AUD supplier rows only. Deep
Search, Bulk, Category Hunter and the Fee Calculator stay locked until their
own phases.

## Tests

- `tests/test_au_market_config.py` pins both benches and the public record.
- `tests/test_serpapi_discovery.py` proves an AU discovery call drops UK
  retailers and searches Google Australia.
- `tests/test_hunter_regressions.py` proves an AU lookup never calls Joybuy.
- `tests/test_au_supplier_bench.py` proves the Analyze supplier step
  instantiates only AliExpress + CJ for AU, and still uses the UK bench by
  default.

No test here reaches the network or spends SerpApi/AliGate quota.
