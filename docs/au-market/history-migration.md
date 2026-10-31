# History currency migration spec

Stored analyses currently carry no marketplace or currency. AU results are
therefore not written to History, because a GBP row and an AUD row would be
compared as if they were the same unit.

## Proposed change

1. Add `marketplace` and `currency` to `products` (default `EBAY_GB` /
   `GBP` for existing rows).
2. `save_analysis_to_db(results)` reads `results["marketplace"]` and
   `results["currency"]` and stores them on the product.
3. `GET /api/history` returns `marketplace` and `currency` per row.
4. The frontend History screen formats money with `formatMoney(value, currency)`
   and never mixes currencies in a total.
5. Enable AU History writes once the migration is deployed. A row without a
   currency is treated as legacy GBP, never as an unknown currency.

## Compatibility

- Existing rows default to GBP.
- Rows created before the migration keep rendering as GBP.
- No cross-currency sum or average is ever shown.