"use client";

import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import { EbayStore } from "@/lib/types";
import { formatGBP } from "@/lib/format";

/**
 * Competitor eBay stores (C11 — up to 4 real seller usernames).
 * `sold_count` is listings observed in the search window, never eBay's sold
 * count, so the backend-supplied label is surfaced verbatim.
 */
export default function EbayStoresCard({
  stores,
}: {
  stores?: EbayStore[] | null;
}) {
  if (!stores?.length) {
    return (
      <Card title="eBay Stores">
        <EmptyState
          title="No competitor stores"
          message="No competitor eBay stores were returned for this analysis."
        />
      </Card>
    );
  }

  return (
    <Card title={`eBay Stores (${stores.length})`}>
      <div className="space-y-2">
        {stores.map((s, i) => (
          <div
            key={`${s.name || "store"}-${i}`}
            className="flex flex-wrap items-center justify-between gap-3 bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm"
          >
            <a
              href={s.url || "#"}
              target="_blank"
              rel="noopener noreferrer"
              title={
                s.url_derived
                  ? `URL derived from seller name (not API-provided): ${s.url}`
                  : s.url
              }
              className="flex items-center gap-2 min-w-0 text-text-primary hover:text-accent-blue"
            >
              <span className="truncate">{s.name || "—"}</span>
              {s.url_derived && (
                <span className="text-[10px] font-semibold uppercase tracking-[0.05em] text-text-dim border border-border rounded px-1 shrink-0">
                  derived
                </span>
              )}
            </a>
            <div className="flex items-center gap-3 whitespace-nowrap">
              <span className="text-text-secondary">
                {s.sold_count ?? "—"}{" "}
                {s.sold_count_label || "observed listings"} ·{" "}
                {formatGBP(s.avg_price)}
              </span>
              <ProvenanceBadge
                provenance={s.provenance}
                label={s.provenance_label}
                title={s.source_name}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
