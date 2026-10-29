# AU Analyze - Phase E1

Phase E1 unlocks the full Analyze pipeline for `EBAY_AU` in AUD. It does not
unlock the standalone fee calculator: that stays behind
`fee_calculator_ready` until Phase E5.

## Two switches, not one

| Field                  | AU now                    | Meaning                                                                                           |
| ---------------------- | ------------------------- | ------------------------------------------------------------------------------------------------- |
| `analyze_ready`        | `true`                    | Analyze may search eBay Australia, the AU supplier bench, and price the verdict with the AU card. |
| `fee_calculator_ready` | `false`                   | `/fees/table` and `/fees/calculate` stay refused for AU.                                          |
| public `fee_table`     | `null`                    | A surface must not mistake "card on file" for "calculator ready".                                 |
| `fee_table_registered` | `au-rate-card-2026-10-09` | The sourced card Analyze uses internally.                                                         |

`marketplaces.analyze_ready()` requires the market's `analyze_ready` flag, a
registered fee card, and a non-empty supplier bench. US, DE and CA therefore
remain search-only.

## The AUD band and demand floors

AU states its own values in `config.MARKETPLACES`:

- band: `A$0.99` to `A$50.00`, user-set in Phase F; never the GBP `5..50`
  band converted at an invented rate;
- demand floors: 30-day `>= 15`, 7-day `>= 10`;
- a 1-day count of `>= 5` is recorded as `momentum_1d` and is advisory, not a
  verdict gate.

`marketplaces.market_filter_defaults()` returns these values, and
`DecisionEngine(marketplace="EBAY_AU")` merges them under any caller values.
The eBay search, sold search and local price gates all receive the same
explicit AUD band. The explicit-band paths no longer call the active GBP
`in_band()`; that was a real bug for any non-GBP market.

## Supplier prices

- **AliExpress**: `AliExpressScraper(marketplace="EBAY_AU")` asks AliGate for
  `country=AU`, `currency=AUD`, `locale=en_AU` per call. AUD rows pass through
  unchanged. A row stating another currency is skipped, not converted.
- **AliExpress browser fallback**: disabled for non-GBP markets. The page does
  not state which currency it rendered, so there is no honest number to carry.
- **CJ Dropshipping**: its API quotes `sellPrice` in USD and exposes no
  currency parameter. AU rows are tagged `currency="USD"` and are excluded from
  the AUD comparison by `analysis_pipeline._supplier_currency_matches()`; the
  response carries a sentence saying how many rows were excluded and that no
  conversion was applied. The UK keeps its historical fixed `0.79` conversion.
- **SerpApi discovery**: rows carry the currency of the Google scope
  (`AUD` for Google Australia), so they can be compared natively.
- **A$0.00 shipping**: `engine/sourcing.py` recognises an explicitly stated
  AUD zero as a known zero, not as "free by assumption".

## History

AU results are not written to History. Stored analyses do not carry a
currency, and keeping AUD prices beside GBP ones would let them be compared.
The response says so in `errors`; the History write is skipped on the normal
and timeout paths.

## UI

Analyze reads `marketplace.analyze_ready` rather than assuming every non-UK
market is search-only. For AU it shows the AUD band, the two-supplier bench,
and the fee-calculator lock notice. Supplier cards and scorecard rows use the
row's own `currency` (`A$` for AUD) instead of hardcoded `formatGBP`.

## Pins

- `tests/test_au_currency.py` - AliGate scope, AUD pass-through, CJ USD
  tagging, Google scope currency, AUD eBay band gates, A$0.00 shipping.
- `tests/test_au_analyze.py` - the two switches, AUD band/floors, AU verdict,
  AU card/private branch, scorecard in A$, pipeline wiring, currency boundary.
- `tests/test_markets.py` - public record and the AU Analyze route; the route
  test proves the AUD filters reach the pipeline and History is skipped.
