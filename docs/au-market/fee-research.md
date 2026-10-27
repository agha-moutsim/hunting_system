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

## 6. Worked examples and category tier membership

### 6.1 The page's four worked examples

Capture #1, "Transaction fee examples". The arithmetic in the last column is
the page's own; it was re-computed here only as a transcription check.

| Plan         | Category                             | Sale amount | Page's calculation                       | Page's total (incl. GST) |
| ------------ | ------------------------------------ | ----------- | ---------------------------------------- | ------------------------ |
| Pro Starter  | Kitchen, Dining, Bar (Tier 2)        | $20         | $0.30 + 13.4% × $20                      | $2.98                    |
| Pro Basic    | Home Appliances (Tier 1)             | $300        | $0.33 + 8.03% × $300                     | $24.42                   |
| Pro Featured | Vehicle Parts & Accessories (Tier 3) | $150        | $0.33 + 11.22% × $150                    | $17.16                   |
| Pro Anchor   | Sporting Goods (Tier 4)              | $5,200      | $0.33 + 11.11% × $4,000 + 2.75% × $1,200 | $477.73                  |

All four totals reproduce exactly, including the merged Starter rate in the
first example. These four rows are the transcription pins for Phase B: a card
that cannot reproduce them is not the published card.

### 6.2 Tier 1 categories (as published)

- Home Appliances (20710)
- Camera (625): Binoculars & Telescopes (28179), Camcorders (11724), Digital
  Cameras (31388), Digital Photo Frames (150044), Film Photography (69323),
  Vintage Movie & Photography (3326)
- Electronics (293): Home Audio Stereos, Components (14969), GPS (156955),
  iPods & MP3 Players (73839), Smart Glasses (178894), Torches (13863),
  Personal Cassette Players (15053), Personal CD Players (15054), Portable
  AM/FM Radios (96954)
- Home Entertainment (172176): Digital Set Top Boxes (96964), DVD & Blu-ray
  Players (175711), DVRs, Hard Drive Recorders (11725), Home Theatre Systems
  (72406), Internet & Media Streamers (168058), Projectors (22610), Satellite
  TV Receivers (96969), TVs (11071), VCRs (15088)
- Phones (15032): Corded Telephones (41373), Cordless Telephones (33929),
  Mobile Phones (9355), PDAs (38331), Smart Watches (178893), Vintage Home
  Phones (182098), Vintage Mobile Phones (182073)
- Video Games & Consoles (1249): Video Game Consoles (139971)

### 6.3 Tier 4 categories (as published)

- Business & Industrial: Business (170638), Industrial (170769)
- Collectables: Antiques (20081), Art (550), Coins (11116), Collectables (1),
  Crafts (14339), Dolls, Bears (237), Pottery, Glass (870), Stamps (260)
- Fashion: Clothing, Shoes, Accessories (11450), Health & Beauty (26395),
  Jewellery & Watches (281)
- Media: Books, Magazines (267), Movies (11232), Music (11233), Video Games &
  Consoles (1249)
- Sporting Goods (888)
- Technology Accessories:
  - Camera (625): Camera, Drone & Photo Accessories (15200), Camera Drones
    (179697), Camera Manuals & Guides (4684), Flashes & Flash Accessories
    (64353), Lenses & Filters (78997), Lighting & Studio (30078), Replacement
    Parts & Tools (182074), Tripods & Supports (30090), Camera Mixed Lots
    (45089), Other Cameras, Accessories (27432)
  - Computers (58058): Computer Cables & Connectors (182094), Computer
    Components & Parts (175673), Drives, Storage & Blank Media (165), Home
    Networking & Connectivity (11176), Keyboards, Mice & Pointers (3676),
    Laptop & Desktop Accessories (31530), Manuals & Resources (3516), Monitor
    Mounts & Stands (51052), Monitor Power Supplies (158845), Monitor
    Replacement Parts (168068), Power Protection, Distribution (86722),
    Printer & Scanner Parts & Accs (182086), Printer Ink, Toner & Paper
    (11195), Projector Replacement Parts (99231), Software (18793), Tablet &
    eBook Reader Accs (176970), Tablet & eBook Reader Parts (180235), Vintage
    Computing (11189), Mixed Lots (259696), Other Computer Monitors & Accs
    (175688), Other Computers & Networking (162)
  - Electronics (293): TV, Video & Audio Accessories (14961), Multipurpose
    Batteries & Power (48446), GPS Accessories (139836), Portable Audio
    Accessories (56169), Radio Communication (1500), Vintage Electronics
    (183077), Mixed Lots (259701)
  - Home Entertainment (172176): Projector Screens (48655), Television
    Accessories (71582)
  - Phones & Accessories (15032): PDA Accessories (175744), Answering Machines
    (139968), Batteries (20034), Caller ID Units (15048), Dummy Mobile Phones
    (136699), Headsets (84079), Mobile Accessories (9394), Mobile Phone Parts
    (43304), Pagers (3314), SIM Cards (29778), Smart Watch Accessories
    (182064), Mobile & Home Phone Mixed Lots (45065)

### 6.4 A transcription finding: parent IDs repeat across tiers

The parent categories **Camera (625)**, **Electronics (293)**, **Home
Entertainment (172176)**, **Phones (15032)** and **Video Games & Consoles
(1249)** appear as group headings in **both** the Tier 1 and Tier 4 lists. The
page resolves this by naming different **leaf** categories under each heading;
it does not state a precedence rule for the parent ID itself.

Consequence for the card: tier resolution must be by leaf category ID, and a
parent ID that is present in both lists must resolve to `known=False` rather
than being assigned to one tier by table order. This is recorded as an open
question in section 10.

## 7. Pro additional fees, currency conversion and GST

### 7.1 Seller-performance fees

Capture #1, "Fees for not meeting seller performance requirements":

- **Below Standard:** if the seller evaluation on the 20th of a month shows the
  seller is not meeting minimum performance standards, a fee of **5.5% (incl.
  GST)** is charged on the total sale amount for items sold in **all
  categories** during the following calendar month.
- If the account has been Below Standard for **four or more consecutive
  months**, the fee increases to **6.6% (incl. GST)** until the seller level
  improves.
- **Very High 'Item not as described' returns:** a fee of **5.5% (incl. GST)**
  on the total sale amount for items sold in the affected categories during the
  following calendar month; **6.6%** after four or more consecutive months.
- If both apply, only the Below Standard fee is charged.

Transcription note for Phase B: the current Pro page states these as a **fee of
5.5% / 6.6% on the total sale amount**, not as a percentage-point increase to
the category FVF. The UK card models its equivalents as extra percentage
points; the AU card must not copy that shape without checking it against this
sentence. The page's older Stores section (applicable until 11 May 2026) did
speak of an increase of percentage points, but that section is historical.

### 7.2 International sales fee

Capture #1:

> If your registered address is in Australia, we charge an international sales
> fee of 1.1% (incl. GST) if the delivery address for the item (entered by the
> buyer during checkout) is outside Australia.

It is calculated on the total amount of the sale (item price + postage and
handling + any tax or other applicable fees). The free-selling page states a
different rate for its branch — **3% (incl. GST)** — and that difference is
transcribed in section 8.2, not merged here.

### 7.3 Dispute fee

Capture #1: **$24.20 (incl. GST)** for each dispute where the seller is found
responsible for a chargeback or other disputed amount.

### 7.4 Seller currency conversion charge

Capture #1 states the charge is **3%** for a seller registered in Australia,
and adds:

> From 1 November 2026, the fee for sellers registered in Australia will
> increase to 3.25%.

The charge applies when eBay converts funds because the seller listed or sold
on another eBay site; the conversion uses eBay's transaction exchange rate,
composed of a base exchange rate plus the conversion charge. It is not a fee on
a normal AUD sale to an Australian buyer, so it does not enter the standard
domestic verdict. The card records both values with their effective dates:
**3.0% through 31 October 2026, 3.25% from 1 November 2026**.

### 7.5 GST

Capture #1's GST section, quoted:

> If your registered address is in Australia, Australian GST of 10% is payable
> on your eBay fees. Unless you provided eBay with your ABN and registered for
> tax exempt status with eBay, we'll charge your eBay fees inclusive of GST, as
> displayed on this page.

So the published card is a **GST-inclusive** card. A tax-exempt seller (ABN
registered with eBay) pays the same fee lines with GST removed; the card will
state that delta rather than silently showing a second set of numbers.

### 7.6 Other terms

- Listing/upgrade fee amounts follow the terms in effect when the listing goes
  live and renews; transaction and international fees follow the terms in
  effect at the time of the sale.
- The page prices listings on eBay.com.au; listing directly on another eBay
  site uses that site's fees.
- All fees are in Australian dollars unless otherwise stated.

## 8. The free-selling (Individual) branch

Capture #3 (page date: "Last updated: 9 October 2026"). This is the branch the
card will use by default for an Australian individual seller.

### 8.1 Eligibility and the no-FVF rule

The page opens:

> It's free for Australia-based sellers with up to $25,000 in sales over the
> past 12 months to sell on eBay.com.au. This means eligible sellers won't pay
> transaction fees (final value fees) when items sell.

Eligibility, quoted as a list:

> To qualify for free selling on eBay.com.au, you need to:
>
> - Have a registration address in Australia, and
> - Sell without an eBay Pro plan, and
> - Sell AU $25,000 or less on eBay in the past 12 months

The measurement is the same 12-full-calendar-month, all-eBay-sites, total-sale
calculation as the Pro page. A seller over AU $25,000 without a Pro plan is
notified on the 20th and moved to **Pro Starter** from the 1st of the following
month; a seller at or under the threshold may stay in free selling or subscribe
voluntarily.

Some fees can still apply inside free selling — the page names optional listing
upgrades and delivery to an overseas address. The label requirement is part of
the same experience:

> Note that as part of our free selling experience, you'll generally have to
> use the prepaid shipping label provided by eBay or buy labels on eBay to send
> your eligible items. From 3 November 2026, you'll also be required to have an
> eBay balance account to receive your sales proceeds.

The page's "Recent and upcoming changes" list adds: from **11 November 2026**,
eBay will begin making prepaid shipping labels available for eligible items as
part of free selling.

**Different fees apply** (the page's own list) when the registration address is
outside Australia, when the seller has a Pro plan, when selling vehicles, or
when selling on eBay Live. Only the first two branches are modelled; the last
two are in the not-modelled list.

### 8.2 Listing fees in free selling

Capture #3, "Fee per listing (incl. GST)". The free-selling branch has one fee
column, not a plan matrix:

| Item                                                     | Fee (incl. GST)                                                |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| Listing in any format — first 250,000 listings per month | FREE                                                           |
| Excess listing (after the monthly allowance)             | $1.00                                                          |
| List in a second category                                | $1.00                                                          |
| Subtitle                                                 | $2.20                                                          |
| Buy It Now added to an auction                           | FREE in most categories; $0.11 in a small number of categories |
| Scheduled listing                                        | FREE in most categories; $0.44 in a small number of categories |

The same small-category list applies: Business > Websites & Businesses for Sale
(11759), Gift Cards & Vouchers > Gift Cards (172009), Home & Garden > Real
Estate (10542), Services (316), Tickets, Travel > Flights (3253), Tickets
(1305), Travel (3252). Relists/renewals follow the same pattern as the Pro
page: automatic auction relists (up to eight) pay once; fixed-price listings
renew monthly and pay the listing/upgrade fee again; a manual relist pays again.

### 8.3 International sales fee in free selling

Capture #3:

> If your registered address is in Australia, we charge an international sales
> fee of 3% (incl. GST) if the delivery address for the item (entered by the
> buyer during checkout) is outside Australia.

This is **3%** on the free-selling page, against **1.1%** on the Pro page. The
two pages are pricing different branches; the card keeps both numbers on their
own branch and never averages them.

### 8.4 Performance, dispute and currency charges

Capture #3 carries the same four charges as the Pro page, with the same
values:

- Below Standard: **5.5% (incl. GST)** on the total sale amount for all
  categories in the following calendar month; **6.6%** after four or more
  consecutive months.
- Very High 'Item not as described' returns: **5.5% (incl. GST)** on the
  affected categories; **6.6%** after four or more consecutive months.
- Dispute fee: **$24.20 (incl. GST)** per dispute.
- Seller currency conversion charge: **3%**, increasing to **3.25%** from
  **1 November 2026** for sellers registered in Australia.

The GST section is also identical: Australian GST of 10% is payable on eBay
fees, displayed inclusive unless the seller has an ABN and tax-exempt status
registered with eBay.

### 8.5 The foreign-seller table (documented, not modelled)

Capture #3 also carries a section for sellers whose registration address is
**outside Australia**. It is transcribed here so the card can state why it is
not used for an AU-registered seller:

| Item                          | Fee (incl. GST)                                          |
| ----------------------------- | -------------------------------------------------------- |
| Fixed fee, all categories     | $0.30 per order                                          |
| Variable FVF, most categories | 13.4% of the sale amount up to $4,000 + 2.5% over $4,000 |
| NFTs                          | 5.5% of the total sale amount                            |
| Services                      | $44.00                                                   |

The page's example ($6,000 sale) totals **$586.30**: $0.30 + 13.4% × $4,000 +
2.5% × $2,000. The card's AU branch uses the AU-registered rates; this table is
kept as a documented alternative, not as a second default.

## 9. The label mandate (Individual branch only)

Capture #4 (no page date line; the live article was read on 27 October 2026 and
repeats the same rules). The page opens:

> Australia-based sellers who are enrolled in free selling are generally
> required to buy a label on eBay when sending items within Australia.

The four exceptions, quoted exactly:

> This doesn't apply to:
>
> - Items sold for less than $20, or over $5,000
> - Items that may be sent in an envelope. These include: trading cards,
>   comics, magazines, coins and banknotes, jewellery, CDs/DVDs/video games,
>   patches, postcards, greeting cards, seeds, stamps, stickers and decals
> - Items where a label isn't available, such as heavy or bulky items
> - Orders where the buyer selected local pickup

Boundary reading, recorded explicitly because a card will encode it:

- **less than $20** means a sale price below $20.00; exactly $20.00 is **not**
  excepted, so the label requirement applies.
- **over $5,000** means a sale price above $5,000.00; exactly $5,000.00 is
  **not** excepted, so the label requirement applies.
- The envelope list is closed on the page — the named item types only.
- "A label isn't available" covers heavy or bulky items; the page gives that as
  an example, not a complete definition.

Operational consequences stated on the same page:

- When listing, the seller can see whether the item is required to use a label
  bought on eBay. After the buyer pays, the seller is prompted to buy the label
  and cannot view the buyer's delivery address or upload tracking manually.
- To offer alternative postage options, the seller needs a **Pro plan** (four
  plans, including a Pro Starter plan with no monthly cost).
- The label's postage cost is deducted from the seller's proceeds or charged to
  the payment method on file. It is **postage**, not an eBay fee.
- From **11 November 2026**, eBay is introducing an improved shipping
  experience for free-selling sellers: for eligible items it determines the
  applicable shipping cost and the seller must use the prepaid Australia Post
  label provided. The article says eBay will notify sellers when this is
  enabled for their account; the current requirement to buy a label on eBay
  remains in the meantime.

**Card implication.** The Individual branch needs a `label_required` predicate
over (sale price, envelope-eligible item type, label availability, local
pickup). When it is true, the cost model must carry postage as a real cost
line. The label price is not a fixed number on the page — it depends on the
parcel — so the engine must record it as an input/absent value with a reason
sentence, never as a guessed average and never as zero.

## 10. Number-to-capture cross-check

Every figure the card will carry, with the capture it came from. Capture IDs
are defined in section 1.

| Figure                                 | Value                                                   | Capture           | Where on the page                      |
| -------------------------------------- | ------------------------------------------------------- | ----------------- | -------------------------------------- |
| Pro Starter monthly                    | No monthly fee                                          | `20261017110035`  | Monthly subscription cost (incl. GST)  |
| Pro Basic monthly                      | $27.45                                                  | `20261017110035`  | same table                             |
| Pro Featured monthly                   | $82.45                                                  | `20261017110035`  | same table                             |
| Pro Anchor monthly                     | $604.95                                                 | `20261017110035`  | same table                             |
| Fixed order fee, Starter               | $0.30 per order                                         | `20261017110035`  | Transaction fee table                  |
| Fixed order fee, Basic/Featured/Anchor | $0.33 per order                                         | `20261017110035`  | Transaction fee table                  |
| Tier 1 FVF                             | 13.4 / 8.03 / 7.26 / 6.82%                              | `20261017110035`  | Transaction fee table                  |
| Tier 2 FVF                             | 13.4 / 10.34 / 9.68 / 9.68%                             | `20261017110035`  | Transaction fee table                  |
| Tier 3 FVF                             | 13.4 / 12.43 / 11.22 / 10.56%                           | `20261017110035`  | Transaction fee table                  |
| Tier 4 FVF                             | 13.4 / 13.09 / 11.77 / 11.11%                           | `20261017110035`  | Transaction fee table                  |
| Starter rowspan                        | 13.4% covers all four tiers                             | `20260513185147`  | HTML `rowspan="4"` on the Starter cell |
| Portion over $4,000                    | 2.5% Starter; 2.75% others                              | `20261017110035`  | Transaction fee table                  |
| NFTs                                   | 5.5% of total sale amount                               | `20261017110035`  | Transaction fee table                  |
| Services                               | $44.00 flat                                             | `20261017110035`  | Transaction fee table                  |
| Worked examples (4)                    | $2.98 / $24.42 / $17.16 / $477.73                       | `20261017110035`  | Transaction fee examples               |
| International fee, Pro                 | 1.1% (incl. GST)                                        | `20261017110035`  | International sales fee                |
| International fee, free selling        | 3% (incl. GST)                                          | `20261012003957`  | International sales fee                |
| Dispute fee                            | $24.20 (incl. GST)                                      | both fee captures | Dispute fees                           |
| Below Standard                         | 5.5%, then 6.6% after 4 months                          | both fee captures | Seller performance                     |
| Very High INR                          | 5.5%, then 6.6% after 4 months                          | both fee captures | Seller performance                     |
| Currency conversion                    | 3% now; 3.25% from 1 Nov 2026                           | both fee captures | Seller currency conversion charge      |
| GST on eBay fees                       | 10%, displayed inclusive                                | both fee captures | Goods and Services Tax                 |
| Free-selling threshold                 | AU $25,000 or less in past 12 months                    | `20261012003957`  | Eligibility for free selling           |
| Free-selling FVF                       | No transaction fees                                     | `20261012003957`  | Opening paragraph                      |
| Free listings                          | 250,000 per month                                       | both fee captures | Listing fees                           |
| Excess listing, free selling           | $1.00                                                   | `20261012003957`  | Listing fee table                      |
| Subtitle                               | $2.20                                                   | both fee captures | Listing fee table                      |
| Label mandate                          | Required for free-selling sellers, with four exceptions | `20260908071955`  | Opening section                        |
| Prepaid labels from 11 Nov 2026        | Announced                                               | `20261012003957`  | Recent and upcoming changes            |

No third-party calculator, blog, forum or aggregator number appears in this
table. Those sources were read only to establish that they disagree; none of
their figures entered the dossier.

## 11. What is not modelled (and why)

| Excluded item                                    | Why it is out                                                                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| eBay Motors / vehicle fees                       | The page says a different schedule applies; vehicles are outside the ten planned features and the AU build.                                      |
| eBay Live selling fees                           | The free-selling page points to a different fee set; live commerce is not in scope.                                                              |
| Classified Ads                                   | The October page removed the fee information because the format is now vehicle-only.                                                             |
| eBay Advertising / Promoted Listings             | Campaign-dependent (percentage after sale or flat fee); not a published fixed rate.                                                              |
| Listing upgrades as a verdict cost               | The card stores guidance (subtitle, BIN, scheduled, excess, second category); a per-sale verdict must not silently add them.                     |
| Seller-performance fees (5.5% / 6.6%)            | They apply only after eBay evaluates the seller; the card records them as a modifier, not as the default verdict.                                |
| Tax-exempt (ABN) fee delta                       | The page states GST is removed for tax-exempt sellers; the card stores the displayed inclusive numbers and records the delta, not a second card. |
| Foreign-registered seller branch                 | Transcribed in 8.5 for completeness; the AU card prices AU-registered sellers.                                                                   |
| Currency conversion charge in a domestic verdict | It applies only when eBay converts funds for another eBay site; a normal AUD sale to an AU buyer does not incur it.                              |
| GST on the seller's own sale price / income tax  | Outside the engine's question (what eBay takes), same stance as the UK card.                                                                     |

## 12. Open questions for Phase B

These are decisions the card build must settle; the dossier records the source
material, not a preference.

1. **Card key date.** The page's own date is 9 October 2026; the capture is
   17 October 2026. The UK card is keyed by the page date
   (`uk-rate-card-2026-09-30`), so the AU card should be
   `au-rate-card-2026-10-09` unless a later page revision is captured before
   the build.
2. **Business plan default.** The card should carry all four Pro plans. The
   default for an AU business seller is **Pro Starter** (the auto-upgrade
   default); Basic/Featured/Anchor are selectable, never assumed.
3. **Parent-category overlap.** Camera (625), Electronics (293), Home
   Entertainment (172176), Phones (15032) and Video Games & Consoles (1249)
   appear in both Tier 1 and Tier 4 lists. The card resolves leaf IDs; an
   ambiguous parent ID must return `known=False`, not first-match.
4. **Performance-fee shape.** Follow the AU sentence (an additional 5.5% /
   6.6% on the total sale amount), not the UK card's percentage-point
   modifiers.
5. **Tax-exempt handling.** Decide whether the ABN/tax-exempt delta is a
   boolean that divides fee lines by 1.1, or a note only. If modelled, tests
   must pin the rounding.
6. **Postage input.** The label mandate makes postage a required real cost for
   eligible individual sales. Confirm how the pipeline receives postage
   (buyer-paid postage vs seller's label cost) and make an absent value
   `None` with a reason sentence.
7. **Rounding.** eBay does not state a rounding rule on these pages; use
   standard two-decimal AUD rounding and state it in the card's provenance.
8. **Currency-conversion effective date.** The card carries 3.0% through
   31 October 2026 and 3.25% from 1 November 2026; the verdict for a domestic
   sale does not use it, but the calculator should be able to show it when a
   cross-site sale is selected.

**Phase A acceptance:** every number above is traceable to an eBay.com.au
capture in section 1; the four worked examples reproduce; no third-party number
is present.
