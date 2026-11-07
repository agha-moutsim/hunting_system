import type { DeepSearchResult } from "@/lib/types";

/**
 * The client-side Bulk CSV, kept out of the page so its money rule can be
 * asserted. A row arrives with 0 as the API's "not measured" default, so a
 * zero price or an unmeasured profit must export as a blank cell — never as
 * 0.00, which a spreadsheet would sum into a real figure.
 */
export type BulkCsvRow = Pick<
  DeepSearchResult,
  | "product_name"
  | "product_category"
  | "verdict"
  | "ebay_avg_price"
  | "best_supplier_price"
  | "profit"
  | "margin"
  | "profit_computed"
  | "ebay_total_sold_30d"
>;

export const BULK_CSV_HEADERS = [
  "Product",
  "Category",
  "Verdict",
  "eBay Avg",
  "Best Supplier",
  "Profit",
  "Margin %",
  "Sold 30d",
] as const;

function cell(value: unknown): string {
  const str = String(value ?? "");
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function priceCell(value: number | null | undefined): string {
  return value != null && value > 0 ? value.toFixed(2) : "";
}

function countCell(value: number | null | undefined): string {
  return value != null && value > 0 ? String(value) : "";
}

function profitCells(row: BulkCsvRow): [string, string] {
  // Same rule the card uses: a supplier cost AND a completed calculation.
  // A measured 0.00 is a real break-even and survives.
  const measured =
    (row.best_supplier_price ?? 0) > 0 && row.profit_computed !== false;
  if (!measured || row.profit == null || row.margin == null) return ["", ""];
  return [row.profit.toFixed(2), row.margin.toFixed(1)];
}

export function bulkCsv(rows: BulkCsvRow[]): string {
  const lines = [
    BULK_CSV_HEADERS.join(","),
    ...rows.map((row) => {
      const [profit, margin] = profitCells(row);
      return [
        cell(row.product_name),
        cell(row.product_category),
        cell(row.verdict),
        priceCell(row.ebay_avg_price),
        priceCell(row.best_supplier_price),
        profit,
        margin,
        countCell(row.ebay_total_sold_30d),
      ].join(",");
    }),
  ];
  return lines.join("\n");
}
