# AU market config - Phase C

Status: the AU fee card is registered for `EBAY_AU`. Analyze uses it in AUD
from Phase E1; the standalone fee calculator is **locked** until Phase E5,
because the fee page still formats money as GBP and has no AU plan/region
controls.

## 1. Two states, never one

The registry carries two separate facts:

| Field                  | Meaning                                                          |
| ---------------------- | ---------------------------------------------------------------- |
| `fee_table`            | The sourced card key the market may price with.                  |
| `fee_calculator_ready` | Whether the standalone fee calculator is wired for the market.   |
| `analyze_ready`        | Whether the full Analyze pipeline may run for the market.        |
| public `fee_table`     | The usable card, or `None` while the calculator is locked.       |
| `fee_table_registered` | The card on file, even while locked.                             |
| `fee_warning`          | The sentence a calculator surface shows instead of a fee figure. |

`EBAY_AU` currently reads:

```python
"fee_table": "au-rate-card-2026-10-09",
"fee_calculator_ready": False,
"analyze_ready": True,   # Phase E1
```

The public selector therefore reports `fee_table: None` and
`fee_table_registered: "au-rate-card-2026-10-09"`. It never presents the
registered card as usable, and it never falls back to the UK card.

## 2. Registry snapshot

| Market    | Currency | Registered card           | Analyze ready | Calculator ready |
| --------- | -------- | ------------------------- | ------------- | ---------------- |
| `EBAY_GB` | GBP      | `uk-rate-card-2026-09-30` | yes           | yes              |
| `EBAY_AU` | AUD      | `au-rate-card-2026-10-09` | yes (E1)      | no (Phase E5)    |
| `EBAY_US` | USD      | none                      | no            | no               |
| `EBAY_DE` | EUR      | none                      | no            | no               |
| `EBAY_CA` | CAD      | none                      | no            | no               |

A market with no card gets the no-card sentence; a market with a registered
but locked card gets the registered-card sentence. Neither is a price.

## 3. Seller defaults

`config.MARKETPLACES[market]["seller_defaults"]` holds the starting branch,
not fee rates:

| Field            | UK         | AU                            |
| ---------------- | ---------- | ----------------------------- |
| `seller_type`    | `business` | `private` (Individual)        |
| `buyer_region`   | `uk`       | `au`                          |
| `seller_plan`    | `None`     | `starter` for a business sale |
| `uk_resident`    | `True`     | `None` (not a UK question)    |
| `vat_registered` | `False`    | `None` (GST is inclusive)     |

`marketplaces.seller_defaults()` returns a copy with these five fields. The
API then applies the request value, then the market default, then
`config.SELLER_PROFILE`; it never copies the UK business branch into AU.

## 4. API boundary

- `GET /api/fees/table` uses the market's own card when `key` is omitted. It
  refuses a table whose currency differs from the market's, so a GBP card
  cannot be read under an AUD heading.
- `POST /api/fees/calculate` resolves and validates the same card before
  pricing, then passes the resolved key to the engine. A foreign-currency
  card is a 422 sentence, not a calculation.
- While `fee_calculator_ready` is false, both routes return 422 for
  `EBAY_AU` with the registered-card sentence.
- `POST /api/analyze` uses `analyze_ready`, not `fee_calculator_ready`, so AU
  runs its full AUD pipeline while the fee routes stay closed.
- `require_uk_market` still guards Deep Search, Bulk and Category Hunter
  because they compare eBay prices with GBP supplier costs. It no longer
  claims the fee card is UK-only; the fee calculator has its own gate.

## 5. Supplier bench (Phase D)

Each market also carries `supplier_bench`: the active source slugs it may use.
UK keeps AliExpress, CJ, B&Q, Toolstation and Joybuy; AU is AliExpress + CJ
only. `marketplaces.supplier_bench()` is the only reader and the public record
exposes it. The bench is policy, not the catalog, and an absent bench is empty

- never the UK list. See `supplier-bench.md`.

The bench does not itself solve supplier currency. Phase E1 scopes AliGate to
AU/AUD, passes AUD rows through, tags CJ's USD rows and excludes them from the
AUD comparison, and disables the unstated-currency browser fallbacks. See
`analyze.md`. Deep Search, Bulk and Category Hunter remain locked.

## 6. Phase E5 flip

When the calculator UI can render AUD, the AU plan selector and the AU
domestic/international region, set:

```python
"fee_calculator_ready": True,
```

for `EBAY_AU`. The public `fee_table` then becomes the AU key, `fee_warning`
becomes `None`, and both fee routes open. Do not flip it earlier: a correct
AUD calculation displayed with a `£` symbol is still a misleading screen.

## 7. Pins

- `tests/test_markets.py` - registry, public selector, refusal sentences.
- `tests/test_au_market_config.py` - seller defaults, card resolution,
  currency boundary, supplier-surface message.
- `tests/test_fees_api.py` - table route, market defaults, cross-currency
  refusal, UK acceptance unchanged.
- `tests/test_fees_au.py` and `tests/test_fees_au_acceptance.py` - the card
  itself, untouched by this phase.
