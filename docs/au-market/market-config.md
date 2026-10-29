# AU market config - Phase C

Status: the AU fee card is registered for `EBAY_AU`, but the calculator is
**locked** until Phase E5. This is deliberate: the card is priced in AUD and
the current fee page still formats money as GBP.

## 1. Two states, never one

The registry carries two separate facts:

| Field                  | Meaning                                                         |
| ---------------------- | --------------------------------------------------------------- |
| `fee_table`            | The sourced card key the market may price with.                 |
| `fee_calculator_ready` | Whether every surface is wired to use that card today.          |
| public `fee_table`     | The usable card, or `None` while the calculator is locked.      |
| `fee_table_registered` | The card on file, even while locked.                            |
| `fee_warning`          | The sentence a surface shows instead of a fee or profit figure. |

`EBAY_AU` currently reads:

```python
"fee_table": "au-rate-card-2026-10-09",
"fee_calculator_ready": False,
```

The public selector therefore reports `fee_table: None` and
`fee_table_registered: "au-rate-card-2026-10-09"`. It never presents the
registered card as usable, and it never falls back to the UK card.

## 2. Registry snapshot

| Market    | Currency | Registered card           | Calculator ready |
| --------- | -------- | ------------------------- | ---------------- |
| `EBAY_GB` | GBP      | `uk-rate-card-2026-09-30` | yes              |
| `EBAY_AU` | AUD      | `au-rate-card-2026-10-09` | no (Phase E5)    |
| `EBAY_US` | USD      | none                      | no               |
| `EBAY_DE` | EUR      | none                      | no               |
| `EBAY_CA` | CAD      | none                      | no               |

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
- `require_uk_market` still guards Deep Search, Bulk and Category Hunter
  because they compare eBay prices with GBP supplier costs. It no longer
  claims the fee card is UK-only; the fee calculator has its own gate.

## 5. Phase E5 flip

When the calculator UI can render AUD, the AU plan selector and the AU
domestic/international region, set:

```python
"fee_calculator_ready": True,
```

for `EBAY_AU`. The public `fee_table` then becomes the AU key, `fee_warning`
becomes `None`, and both fee routes open. Do not flip it earlier: a correct
AUD calculation displayed with a `£` symbol is still a misleading screen.

## 6. Pins

- `tests/test_markets.py` - registry, public selector, refusal sentences.
- `tests/test_au_market_config.py` - seller defaults, card resolution,
  currency boundary, supplier-surface message.
- `tests/test_fees_api.py` - table route, market defaults, cross-currency
  refusal, UK acceptance unchanged.
- `tests/test_fees_au.py` and `tests/test_fees_au_acceptance.py` - the card
  itself, untouched by this phase.
