# Outcome

What exists when this feature work is finished, and how each piece is judged done.

## End state

| Surface               | What it shows                                                         | Source of truth                         |
| --------------------- | --------------------------------------------------------------------- | --------------------------------------- |
| Extension             | Captures silently while browsing; badge shows today's count           | User's signed-in eBay session           |
| Sold panel            | Verified sold counts per item, labelled VERIFIED, with capture date   | `purchase_captures`                     |
| Analyze / Deep search | Same verdicts, every number stamped with origin and age               | provenance + `data_source`              |
| Sources view          | Per product: which field came from where, how stale, what is unknown  | persisted provenance columns            |
| Fee calculator        | Fees, break-even, reverse "sell at X to net Y%"                       | pure arithmetic, published eBay UK fees |
| Alerts                | Price drops and new matching listings on watched items/queries        | `price_alerts`, `saved_searches`        |
| Title helper          | Word and phrase frequency across listings observed for a query        | fetched listing corpus                  |
| Listing age           | "Listed 74 days ago" / "no longer listed since 12 Oct"                | `item_creation_date` + observations     |
| Seller footprint      | Feedback, business vs individual, region, condition mix, price spread | Browse `seller` / `itemLocation`        |
| P&L                   | Real revenue, real profit, real margin                                | `sales`                                 |
| Markets               | EBAY_GB plus at least one of EBAY_US / DE / AU                        | same Browse client, different header    |

## Definition of done for every phase

```
[ ] Tests written and passing
[ ] Backend suite green        python -m pytest tests/ -q
[ ] Frontend suite green       npx vitest run            (from frontend/)
[ ] Typecheck clean            npx tsc --noEmit
[ ] Production build clean     npm --prefix frontend run build
[ ] Verified live against real data, not only unit tests
[ ] One commit, imperative subject, explains WHY not what
[ ] Pushed to origin/main, attributed to the user's GitHub account
```

## Phase outcomes

### Phase A - Passive capture

**Done when:** browsing 10 eBay item pages in a normal session produces 10 `purchase_captures`
rows with no manual clicks, no duplicate row for the same item inside the dedupe window, and the
extension badge reflects the count.
**Proves:** the dataset grows without changing user behaviour.

### Phase B - Rich field persistence

**Done when:** a fresh Analyze run stores creation date, seller feedback score and percentage,
seller account type, seller region and postage cost for observed listings, and a replayed History
run returns identical values.
**Proves:** four later features are possible at no extra API cost.

### Phase C - Verified-first and Sources

**Done when:** a product with a verified capture shows that number as primary with its capture
date; a product without one shows the Browse-derived figure labelled as the search count it is;
the two are visually distinct; and a Sources view lists every field's origin plus an explicit list
of what could not be determined.
**Proves:** the honesty discipline is a feature, not a constraint.

### Phase D - Fee and break-even calculator

**Done when:** fees and break-even match eBay UK's published structure for a business and a
private seller, reverse mode solves for a target margin, and the verdict's `profit`/`margin` come
from the same function - one implementation, not two.
**Proves:** the money numbers are defensible.

### Phase E - Alerts

**Done when:** a tracked item whose price moves produces a `price_alerts` row, a saved search run
produces `search_results` rows, both surface in the UI, and unread alerts are countable.
**Proves:** two dormant tables are fed.

### Phase F - Title helper

**Done when:** a query returns measured token frequencies from the real listings fetched, plus an
80-character meter. No search-volume figure appears anywhere.
**Proves:** the SEO feature is achievable without the one input nobody has.

### Phase G - Listing age and churn

**Done when:** each observed listing shows its age, and listings present in an earlier observation
and absent now are reported as **"no longer listed"** - never "sold".
**Proves:** an honest supply-churn signal that compounds.

### Phase H - Seller footprint

**Done when:** a seller page shows feedback, account type, region, condition mix, active listing
count for a query and asking-price distribution - with no revenue or sold figure on it.
**Proves:** competitor research is possible on the supply side alone.

### Phase I - Own-sales P&L and feedback

**Done when:** sales can be entered or imported, the dashboard shows real revenue, profit and
margin, and a report shows how the C14 matcher thresholds would have scored against actual
outcomes.
**Proves:** the loop.

### Phase J - Markets

**Done when:** a marketplace selector switches all Browse-backed features between EBAY_GB and at
least one other, currency is shown correctly, and no silent cross-currency arithmetic occurs.
**Proves:** the tool is not UK-only by accident.

## Measurable end state

```
purchase_captures        > 500 rows carrying real sold_7d values
listing observations     every Analyze run persists creation date, seller, region, postage
price_alerts             populated, read/unread working
sales                    real sales recorded, P&L non-zero
tables with 0 rows       none that the UI presents
fabricated numbers       0        <- the constraint that defines the project
```
