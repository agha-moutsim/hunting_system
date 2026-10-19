import type { ProvenanceInfo, SourcedFigure } from "./types";

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

/**
 * PHASE C — what PRODUCED a stored figure, as a badge.
 *
 * The tokens are the backend's (api/schemas.py). One of them is verifiable:
 * `purchase_history`, read by the capture extension from the user's own eBay
 * purchase history. Every other number this app holds came from a search of
 * LIVE listings — supply — and is stored under a name that says so rather than
 * being dressed up as a sale.
 *
 * An origin nobody recognises reads `unverified` and names the token in its
 * tooltip. Adding a token here and in api/schemas.py together is the only way
 * a figure gets a new badge; until both exist it reads unverified, which is the
 * safe direction for a badge to fail in.
 */
const ORIGIN_STAMPS: Record<string, ProvenanceInfo> = {
  purchase_history: {
    provenance: "verified",
    label: "eBay purchase history",
    method:
      "read by the capture extension from your own eBay purchase history, in your own signed-in session",
  },
};

/**
 * The badge for one served figure, or null when there is no figure to badge.
 *
 * Null is the important half: a caller cannot stamp a number that was never
 * measured, because there is no figure object to pass in. A figure that IS
 * there but has no recorded origin comes back `unverified` and says so, rather
 * than borrowing the verified look of the field beside it.
 */
export function figureStamp(
  figure?: SourcedFigure | null
): ProvenanceInfo | null {
  if (!figure || figure.value === null || figure.value === undefined) {
    return null;
  }
  const origin = (figure.origin ?? "").trim();
  if (!origin) {
    return {
      provenance: "unverified",
      label: "Source not recorded",
      reason:
        "this row holds the figure without recording which source produced it",
    };
  }
  return (
    ORIGIN_STAMPS[origin] ?? {
      provenance: "unverified",
      label: "Unrecognised source",
      reason: `no badge is defined for origin "${origin}"`,
    }
  );
}
