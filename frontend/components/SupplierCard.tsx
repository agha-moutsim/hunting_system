"use client";

import { MatchAvailabilityFields, ScrapedProduct } from "@/lib/types";
import Badge from "@/components/ui/Badge";
import MatchBadge, {
  SHIPPING_UNKNOWN,
  STOCK_NOT_STATED,
} from "@/components/ui/MatchBadge";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import { formatGBP } from "@/lib/format";

export interface AvailabilityLine {
  /** Dim subject word, e.g. "Stock". Empty when `value` carries its own. */
  label: string;
  /** Rendered as-is. Never a claim the source did not make. */
  value: string;
  /** false = unknown, so it is amber rather than ordinary dim text. */
  known: boolean;
}

const STOCK_LABELS: Record<string, string> = {
  in_stock: "In stock",
  low_stock: "Low stock",
  out_of_stock: "Out of stock",
};

/** A positive number, or null — 0 and NaN both mean "not stated". */
function positive(n?: number | null): number | null {
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
 */
export function describeShipping(
  row: MatchAvailabilityFields
): AvailabilityLine {
  const raw = (row.shipping_raw ?? "").trim();
  const days = positive(row.shipping_days);
  const tail = days != null ? ` · ${days} days` : "";
  if (raw) return { label: "Shipping", value: raw + tail, known: true };
  const cost = positive(row.shipping_cost);
  if (cost != null)
    return { label: "Shipping", value: formatGBP(cost) + tail, known: true };
  return { label: "", value: SHIPPING_UNKNOWN, known: false };
}

function AvailabilityRow({ line }: { line: AvailabilityLine }) {
  return (
    <div className="text-xs text-text-dim mt-1">
      {line.label && (
        <span className="font-semibold uppercase tracking-[0.06em] text-[10px] mr-1.5">
          {line.label}
        </span>
      )}
      <span
        className={line.known ? "font-mono tabular-nums" : "text-accent-amber"}
      >
        {line.value}
      </span>
    </div>
  );
}

export default function SupplierCard({
  supplier,
  ebayPrice,
}: {
  supplier: ScrapedProduct;
  ebayPrice?: number;
}) {
  const delta = ebayPrice != null ? ebayPrice - supplier.price : null;
  const deliveryKnown =
    supplier.delivery_days_min != null && supplier.delivery_days_max != null;
  const stock = describeStock(supplier);
  const shipping = describeShipping(supplier);

  return (
    <a
      href={supplier.url || "#"}
      target="_blank"
      rel="noopener noreferrer"
      className="block bg-bg-secondary border border-border rounded-card shadow-card p-4 hover:border-brand-lime/50 transition-colors duration-150"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <Badge tone="info">{supplier.source}</Badge>
            {supplier.condition && (
              <span className="text-xs text-text-dim">
                {supplier.condition}
              </span>
            )}
            {(supplier.provenance || supplier.verified === false) && (
              <ProvenanceBadge
                provenance={
                  supplier.verified === false
                    ? "unverified"
                    : supplier.provenance
                }
                label={
                  supplier.verified === false
                    ? undefined
                    : supplier.provenance_label
                }
                title={
                  supplier.verified === false
                    ? "API could not verify this supplier"
                    : undefined
                }
              />
            )}
            <MatchBadge
              tier={supplier.match_tier}
              score={supplier.match_score}
              label={supplier.match_label}
              basis={supplier.match_basis}
              method={supplier.match_method}
            />
            {/*
              C13 — provenance says the row was read; `fetch_method` says HOW.
              AliExpress and Amazon UK can only produce a row from a browser
              page read when their credentialed API is unconfigured, and a
              green "Verified" alone reads as though an API returned it.
              Absent/unrecognized `fetch_method` renders nothing: no chip is
              a claim of nothing, never a claim that it was an API.
            */}
            {supplier.fetch_method === "browser" && (
              <Badge
                tone="warn"
                title="Read from the live product page in a browser rather than a credentialed API — this supplier's API is not configured for search. The page really was read; the method is less reliable than an API."
              >
                Browser page read
              </Badge>
            )}
          </div>
          <div className="text-sm text-white font-medium truncate">
            {supplier.title}
          </div>
          <div className="text-xs text-text-dim mt-1">
            {supplier.seller_full_name || supplier.seller || "—"} · Delivery:{" "}
            {deliveryKnown ? (
              `${supplier.delivery_days_min}–${supplier.delivery_days_max} days`
            ) : (
              <ProvenanceBadge
                provenance="unverified"
                title="Delivery not confirmed for this supplier"
              />
            )}
            {supplier.seller_rating && ` · ★ ${supplier.seller_rating}`}
          </div>
          <AvailabilityRow line={stock} />
          <AvailabilityRow line={shipping} />
          {supplier.total_landed_cost != null && (
            <div className="text-xs text-text-dim mt-1">
              <span className="font-semibold uppercase tracking-[0.06em] text-[10px] mr-1.5">
                Total landed
              </span>
              <span className="font-mono tabular-nums">
                {formatGBP(supplier.total_landed_cost)}
              </span>
            </div>
          )}
          {supplier.review_verified && (
            <div className="text-xs text-text-dim mt-1">
              <span className="font-semibold uppercase tracking-[0.06em] text-[10px] mr-1.5">
                Review
              </span>
              <span className="font-mono tabular-nums">
                {supplier.review_rating?.toFixed(1)}
                {supplier.review_count != null
                  ? ` (${supplier.review_count})`
                  : ""}
              </span>
            </div>
          )}
          {supplier.standard_shipping_available === false && (
            <div className="text-xs text-accent-amber mt-1">
              Standard shipping unavailable
              {supplier.standard_shipping_raw
                ? `: ${supplier.standard_shipping_raw}`
                : ""}
            </div>
          )}
          {supplier.sourcing_preferred && (
            <div className="mt-2">
              <Badge tone="pass">Preferred sourcing</Badge>
            </div>
          )}
          {supplier.sourcing_reasons &&
            supplier.sourcing_reasons.length > 0 && (
              <div className="mt-1 text-xs text-text-dim">
                {supplier.sourcing_reasons.join(" · ")}
              </div>
            )}
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-white font-mono tabular-nums">
            {formatGBP(supplier.price)}
          </div>
          {delta != null && (
            <div
              className={`text-xs font-medium font-mono tabular-nums ${
                delta > 0 ? "text-brand-lime" : "text-accent-red"
              }`}
            >
              {delta > 0 ? "+" : ""}
              {formatGBP(delta)} vs eBay
            </div>
          )}
        </div>
      </div>
    </a>
  );
}
