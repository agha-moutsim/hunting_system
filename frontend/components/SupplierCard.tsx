"use client";

import { ScrapedProduct } from "@/lib/types";
import Badge from "@/components/ui/Badge";
import { formatGBP } from "@/lib/format";

export default function SupplierCard({
  supplier,
  ebayPrice,
}: {
  supplier: ScrapedProduct;
  ebayPrice?: number;
}) {
  const delta = ebayPrice != null ? ebayPrice - supplier.price : null;
  const delivery =
    supplier.delivery_days_min != null && supplier.delivery_days_max != null
      ? `${supplier.delivery_days_min}–${supplier.delivery_days_max} days`
      : "⚠️ Unverified";

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
              <span className="text-xs text-text-dim">{supplier.condition}</span>
            )}
            {supplier.verified === false && (
              <Badge tone="warn">⚠️ Unverified</Badge>
            )}
          </div>
          <div className="text-sm text-white font-medium truncate">
            {supplier.title}
          </div>
          <div className="text-xs text-text-dim mt-1">
            {supplier.seller_full_name || supplier.seller || "—"} · Delivery:{" "}
            {delivery}
            {supplier.seller_rating && ` · ★ ${supplier.seller_rating}`}
          </div>
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
