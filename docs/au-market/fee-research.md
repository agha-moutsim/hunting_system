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
