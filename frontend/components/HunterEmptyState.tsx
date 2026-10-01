"use client";

import HotBadge, { hasRealProfit } from "@/components/ui/HotBadge";
import {
  NO_RESULTS_TITLE,
  describeSupplierStatus,
  NO_SUPPLIER_DATA,
  OUT_OF_BAND,
  TIMED_OUT,
  UNKNOWN_PROFIT,
} from "@/components/ui/HotBadge";
import { CategoryProduct, HunterLookupSummary } from "@/lib/types";
import { formatGBP, formatPercent } from "@/lib/format";

/**
 * The empty state.
 *
 * The user asked for a simple "no products found" - and every number in it is
 * a REAL count taken from the run, never invented to make the page look
 * less empty. There are no fake products and no fake suggestions here; the
 * nudges are only things we can act on truthfully: widen a real range, retry
 * after a real timeout, or pick a real category.
 */
export function HunterEmptyState({
  searchText,
  mode,
  summary,
}: {
  searchText?: string;
  mode?: "category" | "keyword";
  summary?: HunterLookupSummary | null;
}) {
  const looked = searchText ? `'${searchText}'` : "this search";

  return (
    <div className="rounded-lg border border-border bg-bg-surface p-6 text-center space-y-3">
      <h3 className="text-base font-semibold text-text-primary">
        {NO_RESULTS_TITLE}
      </h3>

      <p className="text-sm text-text-secondary">
        {summary && summary.scanned > 0 ? (
          <>
            eBay returned {summary.scanned} listing
            {summary.scanned === 1 ? "" : "s"} for {looked} in £
            {summary.price_min}–£{summary.price_max}, but{" "}
            {summary.with_supplier === 0 ? (
              <>
                {summary.no_supplier + summary.timed_out} could not be matched
                to an approved supplier
              </>
            ) : (
              "none of them cleared the profit threshold"
            )}
            .
          </>
        ) : (
          <>
            eBay has nothing for {looked} in the active price range right now.
          </>
        )}
      </p>

      {/* Real next steps only. Each one is something the user can actually
          do, derived from what this run reported. */}
      <ul className="text-xs text-text-secondary space-y-1 list-disc list-inside text-left max-w-md mx-auto">
        {summary && summary.timed_out > 0 && (
          <li>
            {summary.timed_out} supplier lookup
            {summary.timed_out === 1 ? "" : "s"} timed out — run it again, it is
            usually faster the second time.
          </li>
        )}
        {summary && summary.out_of_band > 0 && (
          <li>
            {summary.out_of_band} listing
            {summary.out_of_band === 1 ? " was" : "s were"} outside £
            {summary.price_min}–£{summary.price_max} — widen the price range to
            include more.
          </li>
        )}
        <li>
          Try a broader word — “cordless drill” finds more than an exact model
          number.
        </li>
        <li>
          Or pick one of the categories in the list above to browse a whole
          category instead of searching for one phrase.
        </li>
      </ul>
    </div>
  );
}

/**
 * The profit cell.
 *
 * A row with no supplier has profit 0 and provenance "unverified", which used
 * to render as a confident red GBP0.00 (0.0%). It now renders as a dash with
 * the reason, because that is what a missing value looks like.
 */
export function ProfitCell({ row }: { row: CategoryProduct }) {
  if (!hasRealProfit(row)) {
    return (
      <span
        className="text-text-dim"
        title={
          row.profit_provenance_reason ||
          describeSupplierStatus(
            row.supplier_status,
            row.supplier_status_reason
          )
        }
      >
        {UNKNOWN_PROFIT}
      </span>
    );
  }
  const value = row.profit as number;
  return (
    <span className={value > 0 ? "text-accent-green" : "text-accent-red"}>
      {formatGBP(value)}
      {row.margin != null ? ` (${formatPercent(row.margin)})` : ""}
    </span>
  );
}

/** The supplier cell, which says WHY there is nothing to link to. */
export function SupplierCell({
  row,
  report,
}: {
  row: CategoryProduct;
  report: boolean;
}) {
  if (row.supplier_name) {
    return (
      <a
        href={row.supplier_url || "#"}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent-blue hover:underline"
      >
        {row.supplier_name} {formatGBP(row.supplier_price ?? 0)}
      </a>
    );
  }
  if (!report) return <span className="text-text-dim">…</span>;

  const label =
    row.supplier_status === "timeout"
      ? TIMED_OUT
      : row.supplier_status === "out_of_band"
        ? OUT_OF_BAND
        : NO_SUPPLIER_DATA;
  return (
    <span
      className="text-text-dim"
      title={describeSupplierStatus(
        row.supplier_status,
        row.supplier_status_reason
      )}
    >
      {label}
    </span>
  );
}

/** The demand cell, with the pace that decided whether a row is hot. */
export function DemandCell({ row }: { row: CategoryProduct }) {
  const d7 = row.demand_pace_7d_per_week;
  const base = row.demand_pace_30d_per_week;
  return (
    <span title={row.hot_basis || row.hot_reason || undefined}>
      {row.sold_30d ?? "—"}
      {d7 != null && base != null && (
        <span className="text-text-dim text-xs">
          {" "}
          ({d7}/wk vs {base}/wk)
        </span>
      )}
    </span>
  );
}

export { HotBadge };
