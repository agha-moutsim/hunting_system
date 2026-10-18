# Goal

**Scope: the new feature set only.** This document set does not describe the whole product.
It describes the ten changes being added on top of what already exists. Existing behaviour
(Analyze, Deep search, Hunter, History, Deals, Bulk, Tracker, Watchlist) is out of scope and
appears only where a new feature has to touch it.

## One line

Add features that let eBay Hunter **accumulate verified eBay sales data over time** and answer
the seller's money questions honestly - without ever printing a number it did not measure.

## Why these features

A competitor analysis (ZIK Analytics, 2026-10-19) produced the thesis behind this work:

> ZIK's moat is not its features - it is **ten years of stored listing history** (self-reported:
> 1B+ products, 15M+ stores, since 2017, 159,000 customers, $14-20/month). Every metric they sell
> is a query against snapshots they saved. Their features are reproducible in a weekend; their
> dataset is not purchasable at any price.

So this plan does not copy their feature list. It does two things:

1. **Starts collecting** the one class of data that cannot be faked - sold data, which this
   project can already read _verified_ from eBay's own purchase history via the extension.
2. **Adds the subset of their features reachable without inventing a number** - fees, titles,
   listing age, seller footprint, alerts, own-sales P&L.

Time is the input that cannot be compressed: "how long has this been listed" needs weeks of
history before it means anything. Hence **collection before presentation**.

## The asset that already exists

`extension/` - "eBay Sold History Button" (MV3, plain JS, no build step).

It captures `https://www.ebay.co.uk/bin/purchaseHistory?item={id}`, which renders **only for a
signed-in buyer**, inside the user's own session, and POSTs the raw HTML to the existing
`POST /api/extension/sold-history`. The backend already parses it into real 7-day and 30-day sold
counts and individual sale records, readable via `GET /api/extension/sold-history/{item_id}`.

Current state: `purchase_captures` holds **1 row**. The blocker is not capability - it is that
capture is a three-click manual ritual.

## The ten features

| #   | Feature                                              | Benefit                                                     |
| --- | ---------------------------------------------------- | ----------------------------------------------------------- |
| A   | **Passive capture** - extension fires while browsing | Dataset grows with zero user effort                         |
| B   | **Persist the Browse fields already received**       | Zero extra quota; unlocks G, H, postage-in-margin           |
| C   | **Verified-first + Sources view**                    | The differentiator, currently decorative                    |
| D   | **Fee and break-even calculator**                    | Answers "what must I sell this for to make my margin?"      |
| E   | **Alerts** on watched items and saved searches       | Pull becomes push; feeds two dead tables                    |
| F   | **Title helper** from observed listings              | SEO help without inventing search volume                    |
| G   | **Listing age and churn**                            | "Listed 74 days ago" / "no longer listed" - compounds daily |
| H   | **Seller footprint**                                 | Competitor research from supply alone; no revenue claim     |
| I   | **Own-sales P&L + threshold feedback**               | A loop ZIK structurally cannot have                         |
| J   | **Marketplace expansion**                            | Same code, larger market                                    |

## Non-goals in this scope

- **No sold / revenue / sell-through / search-volume estimates.** Ever. See `constraints.md`.
- **No Shopify features, no ad spy.** Off-niche, enormous lift.
- **No listing or publishing integration.** eBay's Sell API is a different product and moves the
  app from reading the market to operating in it.
- **No crawler on the user's logged-in eBay account.** Account-ban risk. Passive capture of pages
  already being viewed only.
- **No attempt to reach the 6,038 deals** behind eBay's client-assembled AJAX call - measured
  unreachable; 192 fetched listings is the honest ceiling.
- **No rebuilding or restyling existing screens** beyond where a new feature must appear.

## Success

90 days after the first passive capture:

- Verified sold data for every item the user has browsed.
- Listing-age and delisting signals that could not exist on day one.
- Own-sales P&L that ZIK cannot produce for its users.
- **Not one number on any screen that cannot be traced to a measurement.**
