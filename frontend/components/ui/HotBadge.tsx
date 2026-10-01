"use client";

import Badge from "@/components/ui/Badge";

/**
 * Copy for the states where we do NOT have a number.
 *
 * GOLDEN RULE (C1/C13): a missing value is not a zero. These strings exist so
 * that "we have no supplier data" can never be formatted as "GBP0.00" - which
 * is exactly the bug the user hit, where every unsourced row rendered as a
 * confident red GBP0.00 (0.0%).
 */
export const NO_SUPPLIER_DATA = "No supplier data";
export const UNKNOWN_PROFIT = "Not calculated";
export const NO_RESULTS_TITLE = "No products found";
export const TIMED_OUT = "Lookup timed out";
export const OUT_OF_BAND = "Outside price range";

/** The reason a row has no supplier price, in words. */
export function describeSupplierStatus(
  status?: string | null,
  reason?: string | null
): string {
  if (reason && reason.trim()) return reason.trim();
  switch ((status || "").trim()) {
    case "timeout":
      return "Supplier lookup timed out";
    case "out_of_band":
      return "Outside the active price range";
    case "no_supplier":
      return "No approved supplier returned a matching offer";
    default:
      return NO_SUPPLIER_DATA;
  }
}

/**
 * True when this row's profit is a real calculation.
 *
 * A row with `profit_provenance === "unverified"` has a 0 that means "we
 * could not compute this", so it must never be rendered as a figure.
 */
export function hasRealProfit(row: {
  profit_provenance?: string | null;
  profit?: number | null;
}): boolean {
  if (!row || row.profit == null) return false;
  if (row.profit_provenance === "unverified") return false;
  return typeof row.profit === "number";
}

/**
 * The "HOT" badge, shown only when the demand numbers earn it.
 *
 * Computed server-side by hunter/demand_hotness.py from the two eBay sold
 * counts - never decided here, and never shown when the badge would be a
 * guess. An unverified hotness means we had no demand data, and a
 * "not hot" there would be a claim we cannot make.
 */
export default function HotBadge({
  hot,
  basis,
  provenance,
  reason,
}: {
  hot?: boolean | null;
  basis?: string | null;
  provenance?: string | null;
  reason?: string | null;
}) {
  const known = provenance === "verified";
  if (!hot) {
    // No badge at all when not hot, unless we want to explain an absence.
    if (!known && reason) {
      return (
        <span className="text-xs text-text-dim" title={reason}>
          ⚠️ {reason}
        </span>
      );
    }
    return null;
  }
  return (
    <Badge tone="verified" title={basis || undefined}>
      🔥 HOT
    </Badge>
  );
}
