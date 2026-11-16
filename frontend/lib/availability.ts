import { formatMoney } from "./format";
import type { MatchAvailabilityFields } from "./types";

/**
 * The availability lines a supplier card renders, decided in one place.
 *
 * These rules used to live only inside `SupplierCard`, which this repo has no
 * way to test (there is no DOM-testing library). A rule that only a component
 * enforces is a rule nobody can pin, so the stock and shipping claims are pure
 * functions here.
 *
 * GOLDEN RULE: a value is shown only when the source stated one. An unknown
 * stock state says so; a shipping cost of 0.0 is UNKNOWN, not free.
 */
export interface AvailabilityLine {
  /** Dim subject word, e.g. "Stock". Empty when `value` carries its own. */
  label: string;
  /** Rendered as-is. Never a claim the source did not make. */
  value: string;
  /** false = unknown, so it is amber rather than ordinary dim text. */
  known: boolean;
}

/** Fallback copy, shared so every caller renders an unknown the same way. */
export const STOCK_NOT_STATED = "Stock: not stated";
export const SHIPPING_UNKNOWN = "Shipping: unknown";

/**
 * C1 — a replayed supplier row keeps the fact that the source stated a
 * shipping cost, but the analysis stores neither the amount nor its text.
 * Reporting that row as "unknown" would deny evidence the run recorded, and
 * printing a number would invent one. So the line states exactly what is
 * stored: the cost was stated, the amount was not kept.
 */
export const SHIPPING_STATED_NO_AMOUNT = "Cost stated (amount not stored)";

const STOCK_LABELS: Record<string, string> = {
  in_stock: "In stock",
  low_stock: "Low stock",
  out_of_stock: "Out of stock",
};

/** A positive number, or null — 0 and NaN both mean "not stated". */
export function positive(n?: number | null): number | null {
  if (typeof n !== "number" || !Number.isFinite(n) || n <= 0) return null;
  return n;
}

/**
 * GOLDEN RULE: a stock state is only shown when the source stated one.
 * `in_stock` loses to the source's own words, and nothing defaults to
 * "In stock" — an unknown state reads as unknown.
 */
export function describeStock(row: MatchAvailabilityFields): AvailabilityLine {
  const state = (row.in_stock ?? "").trim().toLowerCase();
  if (state && Object.prototype.hasOwnProperty.call(STOCK_LABELS, state)) {
    return { label: "Stock", value: STOCK_LABELS[state], known: true };
  }
  const raw = (row.stock_raw ?? "").trim();
  if (raw) return { label: "Stock", value: raw, known: true };
  return { label: "", value: STOCK_NOT_STATED, known: false };
}

/**
 * GOLDEN RULE: a cost of 0 means NOT CONFIRMED, not free. Only a positive
 * `shipping_cost` becomes a price; the source's own text always wins.
 *
 * A live row carries the text or the amount. A row replayed from storage
 * carries neither, only `shipping_known` — the run's own record that the
 * source stated a cost. That fact is replayed as a stated line rather than
 * dropped into "unknown", and the shipping methods the run stored name the
 * service when there were any.
 */
export function describeShipping(
  row: MatchAvailabilityFields,
  currency = "GBP"
): AvailabilityLine {
  const raw = (row.shipping_raw ?? "").trim();
  const days = positive(row.shipping_days);
  const tail = days != null ? ` · ${days} days` : "";
  if (raw) return { label: "Shipping", value: raw + tail, known: true };
  const cost = positive(row.shipping_cost);
  if (cost != null)
    return {
      label: "Shipping",
      value: formatMoney(cost, currency) + tail,
      known: true,
    };
  if (row.shipping_known === true) {
    const methods = (row.shipping_methods ?? [])
      .map((method) => (method ?? "").trim())
      .filter(Boolean);
    return {
      label: "Shipping",
      value: methods.length
        ? methods.join(" · ")
        : SHIPPING_STATED_NO_AMOUNT,
      known: true,
    };
  }
  return { label: "", value: SHIPPING_UNKNOWN, known: false };
}
