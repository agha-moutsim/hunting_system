# Design

UI and interaction design for the ten new features. Matched to the existing brand kit and
component conventions.

---

## 1. Design principles

1. **The number and its origin are inseparable.** A figure never appears without its provenance
   badge and its observation time. Splitting them is a defect, not a layout choice.
2. **Unknown is a designed state.** Not a blank cell, not a dash, not a zero. It reads
   "not measured" and, where useful, says why.
3. **Supply is never dressed as demand.** No green up-arrows, no "hot", no "trending", no
   fire icons next to a live-listing count.
4. **Quiet by default.** The board rotates and captures without demanding attention. The only
   things that shout are things the user asked to be told about.
5. **Premium means restraint.** Fewer elements, more space, one accent per surface, no decorative
   gradients on data.

## 2. Existing visual language to match

```
background      #27233f      surface   #3b3560     sidebar  #211e35
electric blue   #0d1cc4      acid lime #cbfd03     soft lime #bec97d
purple          #8b5cf6      amber     #ffc857     red       #ff5c5c
neutrals        #ffffff / #b7bbc6 / #8a90a0
fonts           Plus Jakarta Sans (UI) + JetBrains Mono (numbers)
radii           control 6px  /  card 10px
```

Components: `Card(title, action, className)`, `Badge(tone)`, `Button`, `Spinner`,
`EmptyState`, `Metric(label, prov, value, emphasis?)`. Plain `<img>` for images.
`apiFetch<T>` from `@/lib/api`.

Badge tones already available: pass, fail, pending, info, neutral, warn, verified, estimated,
unverified.

---

## 3. New and changed surfaces

### 3.1 Extension popup (Phase A) - CHANGED

A small panel, four states:

```
+------------------------------------------+
|  eBay Sold History                       |
|                                          |
|  Captured today        12                |
|  Last capture          2 min ago         |
|  Backend               connected         |
|                                          |
|  [ Capture this item ]                   |
|  [ Quiet mode: OFF ]                     |
|  Backend base URL  [ http://localhost..] |
+------------------------------------------+
```

- "Captured today" is a count of real rows. No estimate, no projection.
- Quiet mode suspends capture entirely and says so on the badge.
- When the backend is unreachable the panel says so plainly and disables the button, rather than
  failing silently on click.
- The badge shows today's count; when quiet, it shows a muted dot instead of a number.

### 3.2 Verified vs search-count (Phase C) - CHANGED surfaces

Two visually distinct treatments. The difference must survive a glance.

```
VERIFIED                          [ Badge: verified ]
+-----------------------------------------------------+
|  Sold (7d)        8                                  |
|  Read from eBay purchase history - 19 Oct, 14:02     |
+-----------------------------------------------------+

NOT VERIFIED                      [ Badge: estimated ]
+-----------------------------------------------------+
|  Search result count    50                           |
|  In-band New listings a Browse search returned.      |
|  A search-page count, not a sales total.             |
|  No purchase history captured for this item.         |
+-----------------------------------------------------+
```

The second block never uses the word "sold" as a bare label. If a verified capture exists the
search count is demoted to secondary or omitted.

### 3.3 Sources view (Phase C) - NEW

Per product, one table. Every field the screen shows, where it came from, and how old it is.

```
Field              Value        Origin                  Observed
---------------------------------------------------------------
Asking price       GBP 16.99    Browse API by id        19 Oct 00:04
Sold (7d)          8            Purchase-history capture 19 Oct 14:02
Supplier cost      GBP 9.40     Toolstation scrape       18 Oct 22:10
Postage            GBP 0.00     Browse shippingOptions   19 Oct 00:04
---------------------------------------------------------------
Could not be determined
  - Units sold this month         nobody publishes this
  - Competitor revenue            requires sold data at scale
  - Search volume                 eBay does not publish it
```

The "could not be determined" list is a first-class feature. It is the part no competitor ships.

### 3.4 Fee calculator (Phase D) - NEW

Two-column card. Left inputs, right results. Reverse mode is a toggle, not a second screen.

```
Inputs                              Result
  Sale price          [ 24.99 ]       eBay final value fee   GBP 3.50
  Postage charged     [  0.00 ]       Fixed fee              GBP 0.30
  Postage paid        [  3.20 ]       Promoted (2.0%)        GBP 0.50
  Category            [ v Most ]      ----------------------------------
  Promoted rate       [  2.0 ]        Net to you             GBP 17.49
  Seller type         [ v Business]   Supplier cost          GBP 9.40
  VAT registered      [ ]             Profit                 GBP 8.09
  Supplier cost       [  9.40 ]       Margin                 32.4%
                                      Break-even sale price  GBP 13.87
  [ ] Solve for a target margin  [30]  -> sale price must be GBP 23.31
```

Every figure shows the fee table version it used, so a stale table is visible rather than silent.

### 3.5 Alerts (Phase E) - NEW

An inbox, not a toast storm. Unread count in the sidebar next to NAV.

```
[ All ] [ Price ] [ Margin ] [ New matches ]

o  Cafe Du Monde Coffee      price drop   GBP 18.99 -> GBP 15.49    2h ago
o  "garden hose" search      3 new matches over 30% margin          1d ago
*  Bosch drill               margin now 34%                        3d ago
```

Each row names the two values it compared. An alert that cannot state its comparison is not shown.

### 3.6 Saved searches (Phase E) - NEW

Reuses the Hunter filter vocabulary. Row per saved query with last-run time and result count.

### 3.7 Title helper (Phase F) - NEW

```
Query:  garden hose                    Listings analysed: 50

Frequent words        Count     Phrase pairs                 Count
  hose                 48         garden hose                  44
  garden               44         expandable hose              12
  expandable           12         anti-kink hose                9
  anti-kink             9         hose pipe                    7

[ title being built ............................ ]  42 / 80
```

Header states **Listings analysed: 50** because that is the measurement. No search-volume column
exists anywhere in this view.

### 3.8 Listing age and churn (Phase G) - NEW

A compact chip on listing rows, plus a churn list per query.

```
LISTED 74 DAYS AGO        (neutral)
LISTED 2 DAYS AGO         (info)
NO LONGER LISTED          (neutral, with the date last seen)
```

Never "sold", never "ended - sold", never a sold icon. The churn list header reads:
**"Listings observed before, not present in the latest observation."**

### 3.9 Seller footprint (Phase H) - NEW

```
agprefect_09                        [ Badge: neutral ]
  Feedback            99.8%  (12,431)
  Account type        BUSINESS
  Based               GB - WR4
  Observed listings   37 in "garden hose"
  Condition mix       100% New
  Asking prices       GBP 8.99 - GBP 34.99, median GBP 16.99
  Listed              between 3 and 210 days ago
```

There is deliberately **no revenue tile and no sold tile**. The panel states at the foot:
"Observed active listings. Nothing here measures what this seller has actually sold."

### 3.10 P&L (Phase I) - CHANGED surface

Reuses `sales`. The dashboard shows tiles for revenue, profit, margin and units, a six-month
revenue/profit trend, and an explicit "user-declared" badge, because these are the user's own
records rather than observations. A month without declared costs has no profit bar, not a zero.

`/sales` owns entry, CSV import, the sale log and the read-only C14 feedback panel. The panel
replays stored `supplier_matches.match_score` values at a proposed pair of thresholds and lists
only the rows whose tier or visibility changes. It has no control that can change a threshold,
and it states that rows the matcher dropped before storage cannot be replayed.

### 3.11 Marketplace selector (Phase J) - NEW

A small select in the header. When a marketplace other than EBAY_GB is active, every monetary
value shows its currency, and the UI states that fee tables are UK-specific unless one is
provided for that market.

---

## 4. Labelling rules

| Surface       | Permitted                                                        | Forbidden                                                |
| ------------- | ---------------------------------------------------------------- | -------------------------------------------------------- |
| Sold figures  | "Sold (7d)", VERIFIED badge, capture date                        | bare "sold" from a search count                          |
| Live listings | "Active listings", "in-band New listings", "search result count" | popular, trending, best-seller, hot, demand, watch count |
| Delisted      | "No longer listed", "last seen 12 Oct"                           | sold, ended, converted                                   |
| Titles        | "Listings analysed: N", "Frequent words"                         | search volume, searches, traffic                         |
| Sellers       | "Observed listings", feedback, account type                      | revenue, sales, sold, turnover                           |
| Fees          | fee names, break-even, margin                                    | "you will make"                                          |

---

## 5. Empty and unknown states

| Situation                           | Render                                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| No verified capture for an item     | Search-count block with the explanatory sentence and "No purchase history captured for this item." |
| No observation history yet          | "Not enough observations yet - this fills in as the tool is used."                                 |
| Fewer than 2 observations for churn | Suppress the churn list entirely rather than show a zero                                           |
| Fee table out of date               | Banner naming the version in use                                                                   |
| Quota exhausted                     | Say so; do not retry and do not show a stale value as current                                      |

Each of these is a normal, expected state. None of them is an error, and none of them is a blank.
