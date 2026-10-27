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

## 3. The Pro page — who it applies to, and the GST stance

Capture #1 (page date: "Last updated: 9 October 2026"). The page's own opening
states the population it prices:

> The fees on this page apply to sellers with an eBay Pro subscription on
> eBay.com.au and Australia-based sellers with total annual sales of over
> AU $25,000.

The threshold is measured, not guessed. The page states the calculation:

> Each month, we calculate your total sales on eBay using data from the
> preceding 12 full calendar months. […] We add up your sales across all eBay
> sites, using the total amount of each sale (including the item price, postage
> and any applicable tax).

A seller over the threshold without a Pro plan is notified on the 20th of the
month and moved to **Pro Starter** from the 1st of the following month; Pro
Starter has no monthly fee. A seller at or under AU $25,000 may stay in free
selling or subscribe to a Pro plan voluntarily.

**GST stance, quoted:**

> Fees on this page are displayed inclusive of Australian GST. If you have
> registered for tax exempt status with eBay, we won't apply GST to your eBay
> fees.

The same page's GST section adds: Australian GST of 10% is payable on eBay fees;
unless the seller has provided an ABN and registered for tax-exempt status, fees
are charged inclusive of GST **as displayed**. A tax-exempt business seller
therefore pays less than the displayed number; the card stores the displayed
(inclusive) number and records the exemption as a documented delta, not as a
second rate card.

**Currency and scope, quoted:**

> All fees are in Australian dollars, unless otherwise stated.

> The fees on this page apply to listings on eBay.com.au. If you list an item
> directly on another eBay site (e.g. eBay.com or eBay.co.uk), the fees for that
> site will apply.

The page also names what it does **not** price: vehicles (eBay Motors), eBay
Live, and Classified Ad listings (the latter now vehicle-only). Those are
recorded in the not-modelled list in section 10.

## 4. Pro subscriptions and listing fees

Capture #1. The page's own table heading is "Monthly subscription cost (incl.
GST)":

| Plan         | Monthly subscription (incl. GST) |
| ------------ | -------------------------------- |
| Pro Starter  | No monthly fee                   |
| Pro Basic    | $27.45                           |
| Pro Featured | $82.45                           |
| Pro Anchor   | $604.95                          |

Listing and optional upgrade fees, transcribed from the same page's "Fee per
listing (incl. GST)" table. All sellers (Pro and free selling alike) get
**250,000 free listings per month** on eBay.com.au; limits and category
exclusions still apply.

| Item                                                                             | Pro Starter                                                    | Pro Basic | Pro Featured | Pro Anchor |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------- | ------------ | ---------- |
| Auction or fixed price listing (first 250,000/month, most categories)            | FREE                                                           | FREE      | FREE         | FREE       |
| Excess listing (after the monthly allowance, and in the listed small categories) | $1.00                                                          | $0.06     | $0.06        | $0.06      |
| List in a second category                                                        | $1.00                                                          | $0.06     | $0.06        | $0.06      |
| Subtitle                                                                         | $2.20 (see note)                                               | —         | —            | —          |
| Buy It Now added to an auction                                                   | FREE in most categories; $0.11 in a small number of categories | $0.55     | $0.55        | $0.55      |
| Scheduled listing                                                                | FREE in most categories; $0.44 in a small number of categories | same      | same         | same       |

Notes on the table:

- **Subtitle ambiguity, recorded not resolved.** The captured row carries a
  single `$2.20` cell with `colspan="2"` and no further cells; the page does not
  state a per-plan subtitle price. The dossier records "$2.20" and flags the
  plan attribution as unstated in the capture. Listing upgrades are guidance,
  not a per-sale fee, so this cannot affect a verdict.
- The small-category list for the $0.11 / $0.44 upgrades is published on the
  page: Business > Websites & Businesses for Sale (11759), Gift Cards &
  Vouchers > Gift Cards (172009), Home & Garden > Real Estate (10542), Services
  (316), Tickets, Travel > Flights (3253), Tickets (1305), Travel (3252).
- **Relists and renewals:** auction-style listings may auto-relist up to eight
  times with no extra listing fee; fixed-price listings are "Good 'Til
  Cancelled" and renew monthly with the listing/upgrade fee charged again;
  a manual relist pays the fees again.
- **eBay Advertising** is campaign-dependent (a chosen percentage after the
  sale, or an upfront flat fee). It is not a fixed rate and is not modelled.
- The October capture no longer carries the Classified Ad row (the page states
  that format is now vehicle-only); the May capture's $21.99 / $54.99 figures
  are therefore historical and are not transcribed into the card.

## 5. The Pro transaction-fee table

Capture #1, "Transaction fee type / All fees incl. GST". The table has two
parts: a fixed order fee, then a variable final value fee (FVF) that depends on
the listing category and the Pro plan.

**Fixed order fee** — applies to all transactions, in addition to the variable
fee:

| Plan         | Fixed order fee (incl. GST) |
| ------------ | --------------------------- |
| Pro Starter  | $0.30 per order             |
| Pro Basic    | $0.33 per order             |
| Pro Featured | $0.33 per order             |
| Pro Anchor   | $0.33 per order             |

**Variable final value fee** — calculated per item on the total amount of the
sale up to $4,000; the portion above $4,000 is charged at a lower rate:

| Tier   | Definition on the page                                                                                             | Starter | Basic  | Featured | Anchor |
| ------ | ------------------------------------------------------------------------------------------------------------------ | ------- | ------ | -------- | ------ |
| Tier 1 | Items in the Home Appliances and Technology Devices categories                                                     | 13.4%   | 8.03%  | 7.26%    | 6.82%  |
| Tier 2 | All items excluding Tier 1, Tier 3, Tier 4, NFTs and Services                                                      | 13.4%   | 10.34% | 9.68%    | 9.68%  |
| Tier 3 | Items in Vehicle Parts & Accessories categories (131090)                                                           | 13.4%   | 12.43% | 11.22%   | 10.56% |
| Tier 4 | Items in Business & Industrial, Collectables, Fashion, Media, Sporting Goods and Technology Accessories categories | 13.4%   | 13.09% | 11.77%   | 11.11% |

The portion of the sale over $4,000: **2.5%** for Pro Starter, **2.75%** for
Pro Basic, Featured and Anchor.

Two flat rows sit outside the tiers, both stated for all plans:

| Category                   | Fee                           |
| -------------------------- | ----------------------------- |
| Non-fungible tokens (NFTs) | 5.5% of the total sale amount |
| Services                   | $44.00 flat                   |

**Why Starter is 13.4% in every tier.** In the captured HTML the 13.4% cell
carries `rowspan="4"`; it is one cell covering all four tier rows, not a Tier 1
value with three missing plan columns. The page's own example confirms the
reading: Pro Starter, Kitchen, Dining, Bar (Tier 2), $20 sale →
`$0.30 + 13.4% x $20 = $2.98`. A plain-text scrape of the Tier 2–4 rows shows
only three numbers because the Starter cell is merged above them; the card must
encode the merged value explicitly.

**What the fee is charged on** (page's "When calculating the total amount of the
sale per item"):

- item price = winning bid, Buy It Now price, or agreed offer price; it excludes
  the value of any eBay voucher, coupon or discount applied by the buyer at
  checkout;
- postage includes postage charges, handling fees and additional services paid
  by the buyer (e.g. Signature on Delivery);
- an order is any number of items bought by the same buyer at checkout with the
  same delivery method;
- if the buyer redeems a coded coupon provided by the seller, the fee is
  calculated on the discounted total sale amount.

Two further rules from the same page:

- a listing in two categories is charged the **higher** of the two final value
  fees;
- if the item does not sell, no FVF is normally due; if the seller offers or
  references contact information to trade outside eBay, the FVF is based on the
  higher of the fixed price, auction start price, Buy It Now price, reserve price
  or the price identified between buyer and seller.
