# AU fee research — eBay Australia's published selling fees

> Date: **27 October 2026** · Status: **Research only — no repo code/config changed**
> Scope: Phase A of the Australian market build — the sourced fee card that
> `engine/fees.py` will carry as `au-rate-card-*`.
> Every number below is transcribed from an eBay.com.au page. No third-party
> calculator, blog or forum post is a source. Where a page states a date, the
> page's own "Last updated" line is quoted with the capture.

## 0. Why this dossier exists

The AU market needs a fee card before any pricing surface can be unlocked, and
the repo's rule is that a fee is never guessed. eBay's live fee pages are
bot-walled to scripted fetches, and third-party AU fee calculators disagree with
each other on the headline rate (13.4%, 12.7%, 13.25%, 13.6% were all observed
in public calculators). The only acceptable input is eBay Australia's own words,
captured with an identifier that can be re-checked.

This dossier is that input. It transcribes the two seller branches eBay AU
publishes — **Business / eBay Pro** and **Individual / free selling** — plus the
label mandate that changes what an individual seller can spend on postage. The
fee card (Phase B) is built from this document, not from memory.

## 1. Source captures

Wayback Machine captures, retrieved 27 October 2026. The capture ID is the
timestamp in the archived URL.

| #   | Page                                                                                  | Capture ID       | Page's own date line                                                         |
| --- | ------------------------------------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------------- |
| 1   | eBay Pro selling fees (`ebay-pro-selling-fees?id=4809`)                               | `20261017110035` | "Last updated: 9 October 2026."                                              |
| 2   | eBay Pro selling fees — earlier capture, used to read the table's `rowspan` structure | `20260513185147` | "This page was updated on 27 March 2026 with new fee terms."                 |
| 3   | Selling fees without a Pro plan (`selling-fees-without-pro-plan?id=4822`)             | `20261012003957` | "Last updated: 9 October 2026."                                              |
| 4   | Buying shipping labels on eBay (`buying-shipping-labels?id=4157`)                     | `20260908071955` | No date line on the article; capture used for the mandate and its exceptions |

Capture URLs:

- `https://web.archive.org/web/20261017110035/https://www.ebay.com.au/help/selling/fees-credits-invoices/ebay-pro-selling-fees?id=4809`
- `https://web.archive.org/web/20260513185147/https://www.ebay.com.au/help/selling/fees-credits-invoices/ebay-pro-selling-fees?id=4809`
- `https://web.archive.org/web/20261012003957/https://www.ebay.com.au/help/selling/fees-credits-invoices/selling-fees-without-pro-plan?id=4822`
- `https://web.archive.org/web/20260908071955/https://www.ebay.com.au/help/selling/shipping-items/labels-packaging-tips/buying-shipping-labels?id=4157`

The live label article was also read on 27 October 2026; it repeats the same
exceptions and adds the 11 November 2026 prepaid-label rollout. That rollout is
also stated on capture #3, so the dossier cites capture #3 for it.

## 2. Reading rules for this dossier

1. **Transcribe, do not infer.** A number that is not on the page is not in the
   card. If a page is ambiguous, the ambiguity is recorded here rather than
   resolved by arithmetic.
2. **GST is inclusive on these pages.** Both fee pages state that the displayed
   fees include Australian GST unless the seller has registered for tax-exempt
   status with an ABN. The card stores the published (GST-inclusive) numbers and
   says so; it does not add a VAT-on-fees line the way the UK card does.
3. **A rowspan is part of the table.** On the Pro page, the Pro Starter cell for
   the tier table carries `rowspan="4"`: 13.4% is the Starter rate for **all
   four tiers**, not only Tier 1. Reading the table as plain rows makes Tier 2
   look like it has three plan columns; it does not.
4. **"Most categories" is a real row.** Tier 2 is defined as every item outside
   Tiers 1, 3, 4, NFTs and Services. An unresolved category therefore defaults to
   Tier 2 with `known=False`, not to an invented average.
5. **Label cost is postage, not an eBay fee.** The mandate restricts how an
   individual seller may send an item; the label price is the carrier's postage
   charge, deducted from proceeds. It belongs in the cost model as postage, and
   must never be priced as zero when the mandate applies.
