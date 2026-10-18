import type { ProvenanceInfo } from "./types";

/**
 * B3 / C13: the label travels with the number.
 *
 * Deep Search's header renders five numbers - monthly sales, sold 30d,
 * sold 7d, eBay average price and the price range - and until now gave a
 * provenance badge to exactly one of the four tiles beneath them
 * (Profit/Margin). The rest reached the screen bare, so a figure the LLM
 * estimated sat next to one the eBay API returned with nothing telling
 * them apart.
 *
 * These helpers exist as pure functions because this repo has no
 * DOM-testing library: vitest can hold the rule here, and the page only
 * has to wire the result in.
 */

/** Every number the deep-search header renders: the three on the meta
 * line, the four tiles (Range spans min and max), and the two the
 * distribution caption restates — its observation count, which is a
 * different quantity from the 30-day count, plus avg and the range.
 * Add one here when you add one to the page, so it cannot ship unstamped. */
export const HEADER_FIELDS = [
  "ebay_items_sold_month",
  "ebay_total_sold_30d",
  "ebay_total_sold_7d",
  "ebay_avg_price",
  "ebay_price_min",
  "ebay_price_max",
  "best_supplier_price",
  "sold_prices",
  "active_prices",
] as const;

export type HeaderField = (typeof HEADER_FIELDS)[number];

/**
 * GOLDEN RULE, the same one ProvenanceBadge applies: a stamp that is
 * missing, empty or unreadable reads as `unverified`. A number is never
 * allowed to reach the screen with no label at all.
 */
const UNSTAMPED: ProvenanceInfo = {
  provenance: "unverified",
  label: "Unverified",
  reason: "no provenance stamp recorded for this field",
};

export function fieldStamp(
  fields: Record<string, ProvenanceInfo> | undefined,
  name: string
): ProvenanceInfo {
  const stamp = fields?.[name];
  if (!stamp || !stamp.provenance) {
    return { ...UNSTAMPED };
  }
  return stamp;
}

export type HeaderStamps = Record<HeaderField, ProvenanceInfo>;

/** A stamp for every header number, so none of them can be rendered bare. */
export function headerStamps(
  fields: Record<string, ProvenanceInfo> | undefined
): HeaderStamps {
  const stamps = {} as HeaderStamps;
  for (const name of HEADER_FIELDS) {
    stamps[name] = fieldStamp(fields, name);
  }
  return stamps;
}
