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
- **Analyze gate** (`api/analyze.py`): now checks `fee_calculator_ready`, not
  the presence of a registered card. A registered AU card no longer makes AU
  run the UK pipeline; AU stays search-only until Phase E1/E5.

## Currency is not solved by the bench

The bench decides **which sources** may answer. It does not convert a supplier
price into AUD.

- `scrapers/aliexpress_api.py` defaults to `GB` / `GBP` / `en_GB`; an AU call
  needs an explicit AU/AUD scope before its prices can be compared with an AUD
  eBay listing.
- `scrapers/cjdropshipping.py` reads CJ's `sellPrice` as USD and converts it to
  GBP at a fixed `0.79`. That is a GBP number; it must not be summed with AUD.

Therefore Phase D does **not** enable AU pricing. The AU Analyze, Deep Search,
Category Hunter and Fee Calculator surfaces stay locked. Phase E must settle a
sourced currency path (or show the supplier price in its own currency with no
cross-currency profit) before any AU supplier row reaches a verdict.

## Tests

- `tests/test_au_market_config.py` pins both benches and the public record.
- `tests/test_serpapi_discovery.py` proves an AU discovery call drops UK
  retailers and searches Google Australia.
- `tests/test_hunter_regressions.py` proves an AU lookup never calls Joybuy.
- `tests/test_au_supplier_bench.py` proves the Analyze supplier step
  instantiates only AliExpress + CJ for AU, and still uses the UK bench by
  default.

No test here reaches the network or spends SerpApi/AliGate quota.
