import type { DemandData, SourceRow } from "./types";
import { figureStamp } from "./fieldProvenance";
import { formatGBP, formatObservedAt } from "./format";

/**
 * PHASE C — a stored demand row turned into the lines the Sources view shows.
 *
 * Two rules, and they are the whole point of the screen:
 *
 *  - a value is a value only if it was measured. Empty collections and absent
 *    keys become null, never a zero and never a dash that reads as one.
 *  - the unknown reason is attached to the ROW, so the "not known" list is
 *    derived from the data rather than written out by hand. Add a field here
 *    and it appears in whichever list its value puts it in.
 *
 * Supply and sales are labelled apart for the same reason they are stored
 * apart: a count of live listings is real, and it is not a sale.
 */

/** Absent, null and "empty" all mean the same thing: nothing was measured. */
function count(values?: number[] | null): string | null {
  return values && values.length > 0 ? `${values.length}` : null;
}

function moneyRange(low?: number | null, high?: number | null): string | null {
  if (low == null || high == null) return null;
  return `${formatGBP(low)} \u2013 ${formatGBP(high)}`;
}

export function demandSourceRows(demand?: DemandData | null): SourceRow[] {
  // The triple is authoritative; the flat key is the older shape, and a figure
  // served without an origin is shown unverified rather than given one.
  const figure =
    demand?.figures?.sold_count_7d ??
    (demand?.sold_count_7d != null
      ? { value: demand.sold_count_7d, origin: null, observed_at: null }
      : null);

  const captureOnly =
    "Only a purchase-history capture can produce a sale price: it is read when " +
    "you open the listing in your own signed-in session with the extension " +
    "installed.";

  return [
    {
      name: "sold_count_7d",
      label: "Sold in the last 7 days",
      value: figure?.value != null ? String(figure.value) : null,
      stamp: figureStamp(figure),
      readAt: figure?.observed_at ? formatObservedAt(figure.observed_at) : null,
      unknownReason:
        "No purchase-history capture for this listing. Open it in your " +
        "browser with the capture extension installed and the next analysis " +
        "reads the figure.",
    },
    {
      name: "sold_count_30d",
      label: "Sold in the last 30 days",
      value:
        demand?.sold_count_30d != null ? String(demand.sold_count_30d) : null,
      stamp: null,
      readAt: null,
      unknownReason:
        "No source this app can reach produces a 30-day sold count: eBay's " +
        "sold-listing search was decommissioned and its Marketplace Insights " +
        "API refuses this app.",
    },
    {
      name: "avg_sold_price",
      label: "Average price a buyer paid",
      value:
        demand?.avg_sold_price != null
          ? formatGBP(demand.avg_sold_price)
          : null,
      stamp: null,
      readAt: null,
      unknownReason: captureOnly,
    },
    {
      name: "sold_price_range",
      label: "Lowest and highest price paid",
      value: moneyRange(demand?.lowest_sold_price, demand?.highest_sold_price),
      stamp: null,
      readAt: null,
      unknownReason: captureOnly,
    },
    {
      name: "sold_prices",
      label: "Individual sale prices",
      value: count(demand?.sold_prices),
      stamp: null,
      readAt: null,
      unknownReason: captureOnly,
    },
    {
      name: "last_sale_date",
      label: "Date of the most recent sale",
      value: demand?.last_sale_date?.trim() || null,
      stamp: null,
      readAt: null,
      unknownReason: captureOnly,
    },
    {
      name: "active_listings_in_band",
      label: "Live listings the search returned",
      value:
        demand?.active_listings_in_band != null
          ? String(demand.active_listings_in_band)
          : null,
      stamp: null,
      readAt: null,
      supply: true,
      unknownReason:
        "No live listing was read for this product, so there is no count to " +
        "show.",
    },
    {
      name: "avg_active_price",
      label: "Average asking price",
      value:
        demand?.avg_active_price != null
          ? formatGBP(demand.avg_active_price)
          : null,
      stamp: null,
      readAt: null,
      supply: true,
      unknownReason:
        "No asking price was read: this needs a completed eBay search for " +
        "this product.",
    },
    {
      name: "active_price_range",
      label: "Lowest and highest asking price",
      value: moneyRange(
        demand?.lowest_active_price,
        demand?.highest_active_price
      ),
      stamp: null,
      readAt: null,
      supply: true,
      unknownReason:
        "No asking price was read: this needs a completed eBay search for " +
        "this product.",
    },
    {
      name: "active_prices",
      label: "Individual asking prices",
      value: count(demand?.active_prices),
      stamp: null,
      readAt: null,
      supply: true,
      unknownReason:
        "No asking price was read: this needs a completed eBay search for " +
        "this product.",
    },
  ];
}
