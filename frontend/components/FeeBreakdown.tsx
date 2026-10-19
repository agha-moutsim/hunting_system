"use client";

import type { ReactNode } from "react";

import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import { formatGBP, formatPercent } from "@/lib/format";
import type { FeeCalculation } from "@/lib/types";

/**
 * Phase D - one sale's fee breakdown, straight from engine/fees.py.
 *
 * Every amount here is a field the engine sent: the itemised lines, the
 * totals, the buffer, the profit and the margin. The component adds no
 * arithmetic - it puts labels beside numbers and nothing else. The fee table
 * that made the figures is named in the header and the footer, so a stale
 * card is visible rather than silent, and the engine's own assumptions
 * (including the category default) travel with the answer.
 */

function Row({
  label,
  rate,
  children,
}: {
  label: string;
  rate?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-sm text-text-secondary">
        {label}
        {rate ? (
          <span className="ml-1.5 font-mono text-[11px] text-text-dim">
            {rate}
          </span>
        ) : null}
      </span>
      <span className="shrink-0 font-mono text-sm tabular-nums text-white">
        {children}
      </span>
    </div>
  );
}

export default function FeeBreakdown({
  calculation,
  title = "Breakdown",
}: {
  calculation: FeeCalculation;
  title?: string;
}) {
  const { fees } = calculation;
  const table = fees.fee_table;
  const category = fees.category;
  const unknownCategory = category !== null && !category.known;

  const profitTone =
    calculation.profit === null
      ? "text-text-dim"
      : calculation.profit > 0
        ? "text-brand-lime"
        : "text-accent-red";

  return (
    <Card
      title={title}
      action={
        <Badge
          tone="neutral"
          title={`Fee table ${table.key} (${table.version})`}
        >
          {table.key}
        </Badge>
      }
    >
      {unknownCategory && (
        <div className="mb-2 flex items-start gap-2 rounded-control border border-accent-amber/30 bg-accent-amber/10 px-2.5 py-2">
          <Badge tone="warn">Stated default</Badge>
          <p className="text-xs leading-relaxed text-accent-amber/90">
            No category was identified, so {category.name} applies. This is a
            stated default, not a reading of your category.
          </p>
        </div>
      )}

      <div className="divide-y divide-border/60">
        {calculation.fee_lines.map((line) => (
          <Row key={line.label} label={line.label} rate={line.rate}>
            {formatGBP(line.amount)}
          </Row>
        ))}
      </div>

      <div className="mt-2 border-t border-border pt-2">
        <Row
          label="Fees total"
          rate={fees.vat_recoverable ? "VAT excluded" : null}
        >
          {formatGBP(fees.fees_cost_total)}
        </Row>
        <Row label="Net after fees">
          {formatGBP(calculation.net_after_fees)}
        </Row>
        <Row label="Supplier cost">
          {calculation.supplier_cost === null ? (
            <span className="text-text-dim">not known</span>
          ) : (
            formatGBP(calculation.supplier_cost)
          )}
        </Row>
        <Row label="Postage paid">
          {calculation.postage_paid_known ? (
            formatGBP(calculation.postage_paid)
          ) : (
            <span className="text-text-dim">not known</span>
          )}
        </Row>
        <Row
          label="Returns buffer"
          rate={`${calculation.risk_buffer_percent}%`}
        >
          {formatGBP(calculation.risk_buffer)}
        </Row>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-control border border-border bg-bg-surface/70 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-dim">
            Profit
          </div>
          <div
            className={`mt-0.5 font-mono text-lg font-bold tabular-nums ${profitTone}`}
          >
            {formatGBP(calculation.profit)}
          </div>
        </div>
        <div className="rounded-control border border-border bg-bg-surface/70 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-dim">
            Margin
          </div>
          <div className="mt-0.5 font-mono text-lg font-bold tabular-nums text-white">
            {formatPercent(calculation.margin)}
          </div>
        </div>
      </div>

      {calculation.profit === null && calculation.profit_missing_reason && (
        <p className="mt-2 text-xs leading-relaxed text-text-secondary">
          {calculation.profit_missing_reason}.
        </p>
      )}

      {calculation.profit !== null && !calculation.profit_is_complete && (
        <p className="mt-2 text-xs leading-relaxed text-accent-amber/90">
          Postage paid was not given, so the profit above is a ceiling - the
          seller&apos;s own postage would come out of it (C1).
        </p>
      )}

      {fees.vat_recoverable && (
        <p className="mt-2 text-xs leading-relaxed text-text-secondary">
          VAT on fees is recoverable and is excluded from the fees total.
        </p>
      )}

      {fees.assumptions.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-text-dim">
            Assumptions
          </div>
          <ul className="space-y-1">
            {fees.assumptions.map((assumption) => (
              <li
                key={assumption}
                className="text-xs leading-relaxed text-text-secondary"
              >
                {assumption}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-4 border-t border-border pt-3 text-[11px] leading-relaxed text-text-dim">
        Priced with{" "}
        <span className="font-mono text-text-secondary">{table.key}</span> -{" "}
        {table.version}
      </p>
    </Card>
  );
}
