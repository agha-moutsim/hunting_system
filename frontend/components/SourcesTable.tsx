"use client";

import type { ProvenanceInfo, SourceRow } from "@/lib/types";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import Badge from "@/components/ui/Badge";
import { infoTitle } from "@/lib/provenance";

/**
 * PHASE C — every figure a stored run holds, and what is NOT known about it.
 *
 * The point of this screen is the second half. A product page shows the numbers
 * that exist; nothing showed the numbers that do NOT, so "no demand" and "we
 * never looked" read the same. The unknown list here is derived from the rows
 * themselves — a row with no value IS an unknown, and its reason travels with
 * it. Nothing in this component decides what is missing; it is handed the
 * evidence and reports what is absent from it.
 */
export default function SourcesTable({ rows }: { rows: SourceRow[] }) {
  const measured = rows.filter((r) => r.value != null);
  const unknown = rows.filter((r) => r.value == null);

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
            Measured
          </span>
          <span className="h-px flex-1 bg-border/40" />
          <span className="font-mono text-[11px] tabular-nums text-text-dim">
            {measured.length} of {rows.length}
          </span>
        </div>

        {measured.length === 0 ? (
          <p className="rounded-card border border-border/40 border-dashed bg-bg-surface/30 px-4 py-5 text-[13px] text-text-dim">
            Nothing was measured for this product.
          </p>
        ) : (
          <div className="grid gap-2">
            {measured.map((row) => (
              <div
                key={row.name}
                className="grid gap-3 rounded-card border border-border/50 bg-bg-surface/40 px-4 py-3 transition-colors duration-200 hover:border-border/80 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-text-primary">
                      {row.label}
                    </span>
                    {row.supply && (
                      <Badge
                        tone="neutral"
                        title="A count of live listings — real, and not evidence that anything sold"
                      >
                        supply, not sales
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 font-mono text-[11px] text-text-dim">
                    {row.name}
                  </div>
                </div>

                <div className="font-mono text-lg font-semibold tabular-nums tracking-tight text-white">
                  {row.value}
                </div>

                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                  {row.stamp && (
                    <ProvenanceBadge
                      provenance={row.stamp.provenance}
                      label={row.stamp.label}
                      title={infoTitle(row.stamp)}
                    />
                  )}
                  {row.readAt && (
                    <span className="font-mono text-[11px] text-text-dim">
                      {row.readAt}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {unknown.length > 0 && (
        <section>
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-accent-amber/90">
              Not known
            </span>
            <span className="h-px flex-1 bg-border/40" />
            <span className="font-mono text-[11px] tabular-nums text-text-dim">
              {unknown.length} of {rows.length}
            </span>
          </div>

          <div className="grid gap-2">
            {unknown.map((row) => (
              <div
                key={row.name}
                className="rounded-card border border-dashed border-border/50 bg-bg-surface/20 px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                  <span className="text-sm text-text-secondary">
                    {row.label}
                  </span>
                  <span className="font-mono text-[11px] text-text-dim">
                    {row.name}
                  </span>
                  <span className="h-px flex-1 bg-border/30" />
                  <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-accent-amber/80">
                    not measured
                  </span>
                </div>
                <p className="mt-1.5 text-[12px] leading-relaxed text-text-dim">
                  {row.unknownReason}
                </p>
              </div>
            ))}
          </div>

          <p className="mt-3 text-[12px] leading-relaxed text-text-dim">
            A field is listed here because it holds no value — not because a
            value was zero, and not because one was estimated in its place. Zero
            is a measurement: a listing with free postage records a shipping
            cost of 0.00, and it appears above.
          </p>
        </section>
      )}
    </div>
  );
}
