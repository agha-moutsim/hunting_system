"use client";

import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import { EbayStore, ProvenanceInfo } from "@/lib/types";
import { describeStoreLink } from "@/lib/storeLinks";
import { formatGBP } from "@/lib/format";

/**
 * Competitor eBay stores (C11 — up to 4 real seller usernames).
 * `sold_count` is listings observed in the search window, never eBay's sold
 * count, so the backend-supplied label is surfaced verbatim.
 *
 * REGRESSION-006: the block's own provenance is shown, because a thin result
 * reads as a healthy one otherwise. A single store stamped "verified" looks
 * identical to four, which is exactly what the user could not distinguish.
 * So the reason travels with the block: too few found, or a search that had
 * to widen past the buying band to find anyone.
 */
export default function EbayStoresCard({
  stores,
  provenance,
}: {
  stores?: EbayStore[] | null;
  provenance?: ProvenanceInfo | null;
}) {
  const reason = provenance?.reason?.trim();

  if (!stores?.length) {
    return (
      <Card title="eBay Stores">
        <EmptyState
          title="No competitor stores"
          message={
            reason ||
            "No competitor eBay stores were returned for this analysis."
          }
        />
      </Card>
    );
  }

  return (
    <Card
      className="bg-bg-secondary"
      title={`Competitor stores (${stores.length}${
        provenance?.max_stores ? ` of ${provenance.max_stores}` : ""
      })`}
    >
      <div className="space-y-2">
        {stores.map((s, i) => {
          const link = describeStoreLink(s);
          return (
            <div
              key={`${s.name || "store"}-${i}`}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-card border border-border/40 bg-bg-surface/40 px-4 py-3 transition-colors duration-200 hover:border-border/70 hover:bg-bg-surface/70"
            >
              {link ? (
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={link.explanation}
                  className="group flex min-w-0 items-center gap-2.5 rounded-control text-text-primary transition-colors duration-200 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand-lime"
                >
                  <span className="truncate font-medium">{s.name || "—"}</span>
                  <span
                    data-store-link-kind={link.kind}
                    className={`shrink-0 rounded-sm border px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.08em] ${
                      link.isConfirmedStorefront
                        ? "border-brand-lime/40 bg-brand-lime/10 text-brand-lime"
                        : "border-border bg-bg-surface text-text-dim"
                    }`}
                  >
                    {link.kindLabel}
                  </span>
                </a>
              ) : (
                // No link we can stand behind — show the name, never a dead
                // href="#" (REGRESSION-007).
                <span className="flex min-w-0 items-center gap-2.5 text-text-secondary">
                  <span className="truncate">{s.name || "—"}</span>
                  <span className="shrink-0 rounded-sm border border-border bg-bg-surface px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
                    no link
                  </span>
                </span>
              )}

              <div className="flex items-center gap-3 whitespace-nowrap font-mono text-[13px] tabular-nums">
                <span className="text-text-secondary">
                  {s.sold_count ?? "—"}{" "}
                  <span className="text-text-dim">
                    {s.sold_count_label || "observed listings"}
                  </span>
                </span>
                <span className="text-white">{formatGBP(s.avg_price)}</span>
                <ProvenanceBadge
                  provenance={s.provenance}
                  label={s.provenance_label}
                  title={link?.reason || link?.explanation || s.source_name}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* REGRESSION-007: the row chip and the badge now agree. A row reads
          "Store" only when the storefront href was observed on an eBay page;
          everything else reads "Seller profile" and carries the reason, so a
          profile page is never presented as a shop. */}

      {/* The block-level stamp. Hidden when everything was found exactly,
          shown whenever the picture is partial - which is information, not
          an apology. */}
      {(reason || provenance?.provenance === "unverified") && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
          <ProvenanceBadge
            provenance={provenance?.provenance ?? "unverified"}
            label={provenance?.label ?? "Unverified"}
          />
          {reason && <span className="min-w-0">{reason}</span>}
        </div>
      )}
    </Card>
  );
}
