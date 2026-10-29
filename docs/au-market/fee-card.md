# AU fee card - `au-rate-card-2026-10-09`

> Phase B of the Australian market build. The card is implemented in
> `backend/engine/fees.py`, registered in `FEE_TABLES`, and is selectable by
> key. Phase C registers it for `EBAY_AU` in `config.MARKETPLACES` but keeps
> `fee_calculator_ready: False` until Phase E5; see
> `docs/au-market/market-config.md` for the two-state rule.
>
> Source dossier: `docs/au-market/fee-research.md`. Every number below comes
> from the eBay.com.au captures recorded there; no third-party calculator is
> a source.

## 1. Identity and provenance

| Field    | Value                                                                                    |
| -------- | ---------------------------------------------------------------------------------------- |
| Key      | `au-rate-card-2026-10-09`                                                                |
| Version  | eBay AU rate card - Pro and free-selling pages updated 2026-10-09                        |
| Currency | `AUD`                                                                                    |
| Tax      | GST at 10%, displayed inclusive                                                          |
| Domestic | `au`                                                                                     |
| Default  | Individual (free selling), Tier 2 category, Pro Starter if business                      |
| Sources  | Pro capture `20261017110035`; free-selling `20261012003957`; label page `20260908071955` |

The two seller branches are separate sections (`business`, `private`) because
they price different populations. They never share a rate by accident.

## 2. Business / eBay Pro

Four plans are carried; Pro Starter is the default. A plan can be named as
`starter`, `Starter` or `Pro Starter`.

| Plan     | Monthly (incl. GST) | Per order | Portion over $4,000 |
| -------- | ------------------: | --------: | ------------------: |
| Starter  |                  $0 |     $0.30 |                2.5% |
| Basic    |              $27.45 |     $0.33 |               2.75% |
| Featured |              $82.45 |     $0.33 |               2.75% |
| Anchor   |             $604.95 |     $0.33 |               2.75% |

The final value fee is charged on the total amount of the sale (item price +
postage). The tier table is:

| Tier   | Starter |  Basic | Featured | Anchor |
| ------ | ------: | -----: | -------: | -----: |
| Tier 1 |   13.4% |  8.03% |    7.26% |  6.82% |
| Tier 2 |   13.4% | 10.34% |    9.68% |  9.68% |
| Tier 3 |   13.4% | 12.43% |   11.22% | 10.56% |
| Tier 4 |   13.4% | 13.09% |   11.77% | 11.11% |

Starter's 13.4% is the captured `rowspan="4"` cell: it applies to all four
tiers. NFTs are 5.5% flat; Services is $44.00 flat per item. Neither takes the
over-$4,000 step.

The Pro international fee is **1.1%** (incl. GST) when the delivery address is
outside Australia. It is not charged on a domestic sale.

## 3. Individual / free selling

The AU default branch. The page states no final value fee for Australia-based
sellers with AU $25,000 or less in sales over the preceding 12 full calendar
months, across all eBay sites, measured on the total sale amount including
item price, postage and tax.

- `fvf_percent` is a stated `0.0`.
- `per_order_fee` is `None`: the page does not state one for this branch, so
  the card does not assume zero.
- 250,000 free listings per month; excess and second-category listings are
  $1.00.
- The international fee is **3%** (incl. GST) outside Australia.
- Over the threshold, the seller is moved to Pro Starter.

## 4. Categories and the ambiguity rule

The card resolves a category by row key or by leaf category ID. Tier 2 is the
published "all other items" row and is the card's stated default
(`default_category_key: "tier-2"`); an unresolved category prices at Tier 2
with `known=False` and a sentence, never at an invented average.

Camera (625), Electronics (293), Home Entertainment (172176), Phones (15032)
and Video Games & Consoles (1249) head **both** the Tier 1 and Tier 4 lists.
The page does not state which tier a listing directly in one of those parents
belongs to, so the card returns the Tier 2 default with `known=False` and
`ambiguous_parent=True`. Their leaf IDs are priced in the tier that names them.
Computers (58058) is a Tier 4 group heading named by only that tier, so it is
carried in Tier 4.

`list_categories(table)` returns UI-ready rows. An AU row also carries
`rates_by_plan` (one label per plan) and `is_default`; Services carries
`flat_fee`. `rate_label(row, plan=...)` can label one plan without materialising
the whole side.

## 5. GST

The AU page quotes fees inclusive of GST at 10%. The card stores those
displayed numbers and never adds a "GST on fees" line:

- `calculate_fees(... )["tax"] == {"name": "GST", "rate": 10.0, "included": True}`
- `vat_on_fees` is `None`
- `fees_quoted_total == fees_gross_total == fees_cost_total` for the fee lines

A seller with an ABN and tax-exempt status registered with eBay pays the same
fee lines with GST removed. That delta is documented in the dossier and in the
card notes; it is not a second card and is not silently applied.

## 6. Label mandate

`fees.label_required(price, ...)` decides the free-selling label rule. It is a
rule, not a fee: when it applies, the seller must buy a label on eBay, and the
label's price is postage.

Four exceptions, from the label page:

1. sale price below $20.00 or above $5,000.00 - exactly $20.00 and exactly
   $5,000.00 remain in scope;
2. an item that may be sent in an envelope (the page's closed list: trading
   cards, comics, magazines, coins and banknotes, jewellery, CDs/DVDs/video
   games, patches, postcards, greeting cards, seeds, stamps, stickers, decals);
3. an item where a label is not available, such as heavy or bulky items;
4. an order where the buyer selected local pickup.

The predicate returns `required` as `True`, `False` or `None`; an unread price
is `None` with a reason, never a zero. Omitted item facts are named in
`assumptions`. The label's postage cost is not added to the fee total.

## 7. Shared seller charges

These are stated on both fee pages with the same values, so they live at the
card level:

- Below Standard: **5.5%** on the total sale amount, **6.6%** after four or
  more consecutive months.
- Very High 'Item not as described': **5.5%**, **6.6%** after four months.
- If both apply, only the Below Standard fee is charged.
- Dispute fee: **$24.20** (incl. GST).
- Currency conversion: **3.0% through 31 October 2026**, **3.25% from
  1 November 2026**; only when eBay converts funds for a listing or sale on
  another eBay site, not a domestic AUD sale.

The performance fees are carried as data and are **not** applied to a default
verdict. Their shape is "an additional percent of the total sale amount", not
the UK card's percentage-point modifiers.

## 8. What the card does not price

eBay Motors / vehicles, eBay Live, Classified Ads, eBay Advertising /
Promoted Listings campaigns, listing upgrades as a verdict cost, the
tax-exempt ABN delta as a second set of numbers, the foreign-registered seller
branch, and GST on the seller's own sale price. Each is recorded in the
dossier's not-modelled table.

## 9. Using it

```python
from engine import fees

# Individual (the AU default): 0% FVF, GST-inclusive, no international fee
fees.calculate_fees(100.0, fee_table=fees.AU_RATE_CARD_TABLE)

# Business, Pro Basic, Tier 1 leaf, domestic
fees.calculate_fees(
    300.0,
    seller_type="business",
    seller_plan="basic",
    category=20710,
    fee_table=fees.AU_RATE_CARD_TABLE,
)

# The whole money layer carries the same plan
fees.sale_outcome(
    20.0,
    supplier_cost=5.0,
    seller_type="business",
    seller_plan="starter",
    category="tier-2",
    fee_table=fees.AU_RATE_CARD_TABLE,
)

# The label rule, not a fee
fees.label_required(100.0, fee_table=fees.AU_RATE_CARD_TABLE)
```

`buyer_region=None` resolves to the card's domestic region, so an AU sale does
not pay the international fee by omission. `seller_type=None` resolves to the
card's default seller type (Individual for AU); `seller_plan=None` resolves to
Pro Starter for a business seller.

## 10. Phase C / E hand-off

- Phase C is complete: `EBAY_AU` carries `fee_table:
"au-rate-card-2026-10-09"` and `fee_calculator_ready: False`. The public
  selector reports `fee_table: None`, `fee_table_registered` names the card,
  and both fee routes stay 422 until the switch flips. The fee API now takes
  `seller_plan` and defaults `buyer_region` from the marketplace, never from
  the UK-shaped `SELLER_PROFILE`.
- Phase E5: complete. `fee_calculator_ready` is `True`, the public
  `fee_table` is the AU key, and the calculator renders AUD, the plan
  selector and the domestic/international region.
- Phase F: the calculator UI can render `rates_by_plan` and `is_default` from
  `list_categories(table)` and show `label_required(...)` as a rule row, not a
  fee line.

## 11. Acceptance

`tests/test_fees_au.py` pins the card's provenance, every tier rate, plan
metadata, the free-selling branch, the label predicate, GST, international
fees, plan materialisation, the category default and ambiguity, and the four
worked examples. `tests/test_fees_au_acceptance.py` runs the four examples,
the refusals and the layer agreement end to end. The UK card's pins in
`tests/test_fees.py` and `tests/test_fees_api.py` remain green.
