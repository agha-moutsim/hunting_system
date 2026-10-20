"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Input, { Label } from "@/components/ui/Input";
import FeeBreakdown from "@/components/FeeBreakdown";
import Spinner from "@/components/Spinner";
import {
  DEFAULT_FEE_FORM,
  buildFeeRequest,
  calculateFees,
  feeFormFromProfile,
  fetchFeeTable,
  type FeeFormState,
  type FeeMode,
} from "@/lib/fees";
import { useMarketplace } from "@/lib/marketplace";
import { formatGBP, formatPercent } from "@/lib/format";
import type {
  FeeCalculateRequest,
  FeeCalculation,
  FeeReverseResult,
  FeeSolveCheck,
  FeeTableResponse,
} from "@/lib/types";

/**
 * PHASE D — the fee and break-even calculator.
 *
 * One sale, priced by engine/fees.py through /api/fees/calculate: the page
 * owns no fee constants and does no arithmetic. Forward mode answers what a
 * price earns; reverse mode answers what price earns a target margin (the
 * same engine, solved); break-even is that solve at a 0% target. Every panel
 * names the fee table that made its figures, and unknown inputs stay unknown —
 * a blank supplier means "profit not computed", a blank postage reading means
 * the profit shown is a ceiling, and no category means the engine's stated
 * default, not a guess.
 */

const SELECT_CLASS =
  "w-full bg-bg-surface border border-border rounded-control px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:border-accent-blue";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
      {hint && (
        <p className="mt-1 text-[11px] leading-relaxed text-text-dim">{hint}</p>
      )}
    </div>
  );
}

function ModeToggle({
  mode,
  onChange,
}: {
  mode: FeeMode;
  onChange: (mode: FeeMode) => void;
}) {
  const base = "px-3 py-1.5 text-xs font-semibold transition-colors";
  const active = "bg-accent-blue text-white";
  const idle = "text-text-secondary hover:bg-bg-surface hover:text-white";
  return (
    <div className="flex overflow-hidden rounded-control border border-border">
      <button
        type="button"
        aria-pressed={mode === "forward"}
        className={`${base} ${mode === "forward" ? active : idle}`}
        onClick={() => onChange("forward")}
      >
        Sale → fees
      </button>
      <button
        type="button"
        aria-pressed={mode === "reverse"}
        className={`${base} ${mode === "reverse" ? active : idle}`}
        onClick={() => onChange("reverse")}
      >
        Target → price
      </button>
    </div>
  );
}

export default function FeesPage() {
  const { marketplace } = useMarketplace();
  const marketBlocked = !marketplace.fee_table;
  const [table, setTable] = useState<FeeTableResponse | null>(null);
  const [tableError, setTableError] = useState<string | null>(null);
  const [form, setForm] = useState<FeeFormState>(DEFAULT_FEE_FORM);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forward, setForward] = useState<FeeCalculation | null>(null);
  const [reverse, setReverse] = useState<FeeReverseResult | null>(null);
  const [breakEven, setBreakEven] = useState<FeeSolveCheck | null>(null);

  useEffect(() => {
    if (marketBlocked) {
      // The only fee table is the UK card. Loading it under a US heading and
      // letting a reader apply it would be the exact cross-currency error
      // Phase J forbids, so the page shows the sentence instead.
      setTable(null);
      setTableError(null);
      setForward(null);
      setReverse(null);
      setBreakEven(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchFeeTable();
        if (cancelled) return;
        setTable(data);
        setForm(feeFormFromProfile(data.profile));
      } catch (e) {
        if (!cancelled) {
          setTableError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [marketBlocked, marketplace.id]);

  function patch(update: Partial<FeeFormState>) {
    setForm((current) => ({ ...current, ...update }));
  }

  /** The 0%-target solve, on the same engine and inputs as the sale. */
  async function loadBreakEven(request: FeeCalculateRequest) {
    try {
      const data = await calculateFees(request);
      if (data.mode === "reverse" && data.achievable && data.check) {
        setBreakEven(data.check);
      }
    } catch {
      // The sale is already priced; break-even is extra, and its failure must
      // not erase the answer on screen.
    }
  }

  async function run(e: FormEvent) {
    e.preventDefault();
    if (calculating) return;
    if (marketBlocked) {
      setError(
        marketplace.fee_warning ||
          "No fee table is registered for this marketplace."
      );
      return;
    }
    const built = buildFeeRequest(form);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setCalculating(true);
    setError(null);
    setBreakEven(null);
    try {
      const data = await calculateFees(built.request);
      if (data.mode === "forward") {
        setForward(data.calculation);
        setReverse(null);
        if (built.request.supplier_cost != null) {
          const breakEvenRequest: FeeCalculateRequest = {
            ...built.request,
            target_margin: 0,
          };
          delete breakEvenRequest.sale_price;
          void loadBreakEven(breakEvenRequest);
        }
      } else {
        setReverse(data);
        setForward(data.calculation ?? null);
      }
    } catch (err) {
      setForward(null);
      setReverse(null);
      setError(err instanceof Error ? err.message : "The calculation failed");
    } finally {
      setCalculating(false);
    }
  }

  const mode = form.mode;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="text-xl font-bold text-text-primary">Fee Calculator</h1>
        <p className="mt-1 text-sm text-text-secondary">
          One sale priced by the published eBay UK rate card — from the same
          engine the verdict uses, so the numbers agree by construction.
        </p>
      </div>

      {marketBlocked && (
        <Card className="border-accent-amber/40">
          <div className="text-sm text-accent-amber">
            {marketplace.fee_warning}
          </div>
          <p className="mt-1 text-xs text-text-secondary">
            Switch the marketplace in the header to United Kingdom to use the
            calculator. No fee or profit figure was calculated for{" "}
            {marketplace.label}.
          </p>
        </Card>
      )}

      {table && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-text-dim">
          <span>
            Fee table{" "}
            <span className="font-mono text-text-secondary">
              {table.fee_table.key}
            </span>{" "}
            — {table.fee_table.version}
          </span>
          {table.fee_table.sources.map((source) => (
            <a
              key={source.url}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-secondary underline decoration-border hover:text-white"
            >
              {source.label}
            </a>
          ))}
        </div>
      )}

      {tableError && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">
            The fee table could not be loaded: {tableError}. You can still
            calculate — the engine prices with the same table either way.
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-5 lg:items-start">
        <Card
          title="Inputs"
          className="lg:col-span-2"
          action={
            <ModeToggle mode={mode} onChange={(m) => patch({ mode: m })} />
          }
        >
          <form onSubmit={run} className="space-y-3">
            {mode === "forward" ? (
              <Field label="Sale price (£)">
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="24.99"
                  value={form.salePrice}
                  onChange={(e) => patch({ salePrice: e.target.value })}
                />
              </Field>
            ) : (
              <Field
                label="Target margin (%)"
                hint="The engine solves for the sale price that reaches it."
              >
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="30"
                  value={form.targetMargin}
                  onChange={(e) => patch({ targetMargin: e.target.value })}
                />
              </Field>
            )}

            <div className="grid grid-cols-2 gap-3">
              <Field label="Postage charged (£)">
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.postageCharged}
                  onChange={(e) => patch({ postageCharged: e.target.value })}
                />
              </Field>
              <Field label="Postage paid (£)">
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="3.20"
                  value={form.postagePaid}
                  onChange={(e) => patch({ postagePaid: e.target.value })}
                />
              </Field>
            </div>
            <p className="-mt-1 text-[11px] leading-relaxed text-text-dim">
              A blank postage paid is unknown, not free: the profit is then a
              ceiling and the breakdown says so.
            </p>

            <Field label="Supplier cost (£)">
              <Input
                type="number"
                step="0.01"
                min="0"
                placeholder="9.40"
                value={form.supplierCost}
                onChange={(e) => patch({ supplierCost: e.target.value })}
              />
            </Field>

            <Field
              label="Category"
              hint="No category means Everything Else (12.9%) applies as the engine's stated default."
            >
              <select
                className={SELECT_CLASS}
                value={form.category}
                onChange={(e) => patch({ category: e.target.value })}
              >
                <option value="">No category — stated default applies</option>
                {table?.categories.map((category) => (
                  <option key={category.key} value={category.key}>
                    {category.name} · {category.rate_label}
                  </option>
                ))}
              </select>
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Promoted rate (%)">
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="0"
                  value={form.promotedRate}
                  onChange={(e) => patch({ promotedRate: e.target.value })}
                />
              </Field>
              <Field label="Seller type">
                <select
                  className={SELECT_CLASS}
                  value={form.sellerType}
                  onChange={(e) =>
                    patch({
                      sellerType:
                        e.target.value === "private" ? "private" : "business",
                    })
                  }
                >
                  <option value="business">Business</option>
                  <option value="private">Private</option>
                </select>
              </Field>
            </div>

            <label className="flex items-center gap-2 text-sm text-text-secondary">
              <input
                type="checkbox"
                className="h-4 w-4 rounded-sm border-border bg-bg-surface accent-brand-lime"
                checked={form.vatRegistered}
                onChange={(e) => patch({ vatRegistered: e.target.checked })}
              />
              VAT registered — VAT on fees is recoverable
            </label>

            <div className="pt-1">
              <Button
                type="submit"
                disabled={calculating || marketBlocked}
                className="w-full"
              >
                {calculating
                  ? "Calculating…"
                  : mode === "forward"
                    ? "Calculate fees"
                    : "Solve for the price"}
              </Button>
            </div>
            {error && (
              <p className="text-sm leading-relaxed text-accent-red">{error}</p>
            )}
          </form>
        </Card>

        <div className="space-y-4 lg:col-span-3">
          {calculating && (
            <Card>
              <Spinner label="Pricing the sale…" />
            </Card>
          )}

          {!calculating && reverse && (
            <Card title="Price for your target">
              {reverse.achievable && reverse.price !== null ? (
                <div>
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-dim">
                        List at
                      </div>
                      <div className="mt-0.5 font-mono text-3xl font-bold tabular-nums text-brand-lime">
                        {formatGBP(reverse.price)}
                      </div>
                    </div>
                    <Badge tone="pass">
                      Target {formatPercent(reverse.target_margin)}
                    </Badge>
                  </div>
                  {reverse.check && (
                    <p className="mt-2 text-xs leading-relaxed text-text-secondary">
                      At this price the engine recomputes a profit of{" "}
                      {formatGBP(reverse.check.profit)} on{" "}
                      {formatGBP(reverse.check.net_after_fees)} net after fees.
                    </p>
                  )}
                </div>
              ) : (
                <div>
                  <Badge tone="warn">Not reachable</Badge>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                    {reverse.reason}
                  </p>
                </div>
              )}
            </Card>
          )}

          {!calculating && forward && <FeeBreakdown calculation={forward} />}

          {!calculating && forward && breakEven && (
            <Card title="Break-even">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <span className="text-sm text-text-secondary">
                  Lowest sale price that does not lose money
                </span>
                <span className="font-mono text-lg font-bold tabular-nums text-white">
                  {formatGBP(breakEven.price)}
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-text-dim">
                Solved by the same engine at a 0% target margin and rounded up
                to the penny: at this price the engine recomputes a profit of{" "}
                {formatGBP(breakEven.profit)}. Below it, every sale on these
                costs loses money.
              </p>
            </Card>
          )}

          {!calculating && !forward && !reverse && (
            <Card>
              <p className="text-sm leading-relaxed text-text-secondary">
                Enter a sale on the left and calculate. The breakdown lists
                every fee the engine charged, names the table it priced with,
                and states what it does not know rather than guessing.
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
