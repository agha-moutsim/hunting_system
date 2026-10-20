/**
 * Phase I — the sales contract and the small amount of presentation logic
 * that must not turn an absent value into a zero.
 *
 * The backend owns every calculation: profit, margin, monthly totals and
 * threshold counts. This module only shapes a form submission, calls the API,
 * and formats labels. `buildSaleRequest` deliberately refuses a blank cost
 * instead of `Number("")` turning it into 0, because that is exactly how an
 * unknown fee becomes invented profit.
 */

import { apiDelete, apiFetch, apiPost, apiPut } from "./api";
import type {
  Sale,
  SaleCreateRequest,
  SalesCsvImportResult,
  SalesListResponse,
  SalesSummary,
  ThresholdReplay,
  ThresholdTier,
} from "./types";

export const SALES_DECLARATION =
  "These are your own sales records, entered by you. They are not eBay observations.";

export const THRESHOLD_SOURCE = "Stored C14 matcher outcomes";

export const THRESHOLD_LIMITATION =
  "Supplier rows the matcher dropped were never stored, so a lower threshold's newly admitted rows cannot be replayed. Only rows already in supplier_matches appear here.";

export interface SaleFormValues {
  product_name: string;
  category: string;
  sale_price: string;
  supplier_cost: string;
  shipping_cost: string;
  ebay_fees: string;
  quantity: string;
  sale_date: string;
  buyer_location: string;
  notes: string;
}

export const EMPTY_SALE_FORM: SaleFormValues = {
  product_name: "",
  category: "",
  sale_price: "",
  supplier_cost: "",
  shipping_cost: "",
  ebay_fees: "",
  quantity: "1",
  sale_date: "",
  buyer_location: "",
  notes: "",
};

/** Today as YYYY-MM-DD in the browser's local calendar, not UTC. */
export function todayIsoLocal(now: Date = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function saleDateIsValid(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function requiredNumber(
  label: string,
  raw: string,
  { allowZero }: { allowZero: boolean }
): { value: number } | { error: string } {
  const cleaned = raw.trim().replace(/£/g, "").replace(/,/g, "");
  if (cleaned === "") {
    return {
      error: `${label} is required. Enter 0 only if it really was zero.`,
    };
  }
  const value = Number(cleaned);
  if (!Number.isFinite(value)) {
    return { error: `${label} must be a number.` };
  }
  if (value < 0) {
    return { error: `${label} cannot be negative.` };
  }
  if (!allowZero && value <= 0) {
    return { error: `${label} must be greater than zero.` };
  }
  return { value };
}

export type SaleRequestResult =
  { ok: true; payload: SaleCreateRequest } | { ok: false; error: string };

/**
 * A blank cost is a refusal, not a zero. Costs are per unit and the backend
 * multiplies them by `quantity`; the date is required because it decides the
 * month in `monthly_stats`.
 */
export function buildSaleRequest(values: SaleFormValues): SaleRequestResult {
  const productName = values.product_name.trim();
  if (!productName) {
    return { ok: false, error: "Product name is required." };
  }

  const salePrice = requiredNumber("Sale price", values.sale_price, {
    allowZero: false,
  });
  if ("error" in salePrice) return { ok: false, error: salePrice.error };

  const supplierCost = requiredNumber("Supplier cost", values.supplier_cost, {
    allowZero: true,
  });
  if ("error" in supplierCost) return { ok: false, error: supplierCost.error };

  const shippingCost = requiredNumber("Shipping cost", values.shipping_cost, {
    allowZero: true,
  });
  if ("error" in shippingCost) return { ok: false, error: shippingCost.error };

  const ebayFees = requiredNumber("eBay fees", values.ebay_fees, {
    allowZero: true,
  });
  if ("error" in ebayFees) return { ok: false, error: ebayFees.error };

  const quantityNumber = Number(values.quantity.trim());
  if (
    values.quantity.trim() === "" ||
    !Number.isInteger(quantityNumber) ||
    quantityNumber < 1
  ) {
    return {
      ok: false,
      error: "Quantity must be a whole number of 1 or more.",
    };
  }

  if (!saleDateIsValid(values.sale_date)) {
    return {
      ok: false,
      error: "Sale date must be a real date in YYYY-MM-DD form.",
    };
  }

  return {
    ok: true,
    payload: {
      product_name: productName,
      category: values.category.trim(),
      sale_price: salePrice.value,
      supplier_cost: supplierCost.value,
      shipping_cost: shippingCost.value,
      ebay_fees: ebayFees.value,
      quantity: quantityNumber,
      sale_date: values.sale_date.trim(),
      buyer_location: values.buyer_location.trim(),
      notes: values.notes.trim(),
    },
  };
}

export function fetchSalesSummary(
  days = 30,
  months = 6
): Promise<SalesSummary> {
  return apiFetch<SalesSummary>(
    `/api/sales/summary?days=${days}&months=${months}`
  );
}

export function fetchSales(
  limit = 500,
  offset = 0
): Promise<SalesListResponse> {
  return apiFetch<SalesListResponse>(
    `/api/sales?limit=${limit}&offset=${offset}`
  );
}

export function createSale(payload: SaleCreateRequest): Promise<Sale> {
  return apiPost<Sale>("/api/sales", payload);
}

export function updateSale(
  id: number,
  payload: SaleCreateRequest
): Promise<Sale> {
  return apiPut<Sale>(`/api/sales/${id}`, payload);
}

export function deleteSale(id: number): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/sales/${id}`);
}

export function importSalesCsv(
  csv: string,
  filename = ""
): Promise<SalesCsvImportResult> {
  return apiPost<SalesCsvImportResult>("/api/sales/import", { csv, filename });
}

export function replayThresholds(
  verified?: number,
  unverified?: number
): Promise<ThresholdReplay> {
  // With no arguments the backend answers with its own current C14 constants.
  // That is the first-load request, so the browser never has to guess them.
  const params = new URLSearchParams();
  if (verified !== undefined) params.set("verified", String(verified));
  if (unverified !== undefined) params.set("unverified", String(unverified));
  const query = params.size ? `?${params}` : "";
  return apiFetch<ThresholdReplay>(`/api/sales/thresholds${query}`);
}

export function tierLabel(tier: ThresholdTier): string {
  if (tier === "verified") return "Confirmed match";
  if (tier === "unverified") return "Not confirmed";
  return "No confirmed match";
}

export function changeLabel(change: string): string {
  const labels: Record<string, string> = {
    verified_to_unverified: "Confirmed → not confirmed",
    verified_to_no_match: "Confirmed → no match",
    unverified_to_verified: "Not confirmed → confirmed",
    unverified_to_no_match: "Not confirmed → no match",
    no_match_to_verified: "No match → confirmed",
    no_match_to_unverified: "No match → not confirmed",
  };
  return labels[change] || change.replaceAll("_", " ");
}

export function formatSaleDate(iso?: string | null): string {
  if (!iso) return "-";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3])
  );
  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function monthlyChartData(summary: SalesSummary): {
  labels: string[];
  revenue: number[];
  profit: (number | null)[];
} {
  return {
    labels: summary.monthly.map((month) => month.label),
    revenue: summary.monthly.map((month) => month.revenue),
    profit: summary.monthly.map((month) => month.profit),
  };
}

export const SALES_CSV_HEADERS =
  "product_name,sale_price,supplier_cost,shipping_cost,ebay_fees,quantity,sale_date,category,buyer_location,notes";

export function salesCsvTemplate(today: string = todayIsoLocal()): string {
  return (
    `${SALES_CSV_HEADERS}\n` +
    `Cordless Drill,100.00,20.00,5.00,10.00,1,${today},Tools,,\n`
  );
}
