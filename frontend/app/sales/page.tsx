"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import Link from "next/link";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Input, { Label } from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { Column } from "@/components/DataTable";
import Spinner from "@/components/Spinner";
import { formatGBP, formatPercent } from "@/lib/format";
import {
  EMPTY_SALE_FORM,
  SALES_CSV_HEADERS,
  SALES_DECLARATION,
  buildSaleRequest,
  changeLabel,
  createSale,
  deleteSale,
  fetchSales,
  formatSaleDate,
  importSalesCsv,
  replayThresholds,
  salesCsvTemplate,
  tierLabel,
  todayIsoLocal,
  type SaleFormValues,
} from "@/lib/sales";
import type {
  Sale,
  SalesCsvImportResult,
  ThresholdDifferenceRow,
  ThresholdReplay,
  ThresholdSweepRow,
} from "@/lib/types";

const BUTTON_LINK =
  "inline-flex items-center justify-center px-4 py-2 rounded-control text-sm font-semibold bg-accent-blue text-white hover:bg-accent-blue-dark transition-colors duration-150";

function initialForm(): SaleFormValues {
  return { ...EMPTY_SALE_FORM, sale_date: todayIsoLocal() };
}

function costCell(sale: Sale): string {
  const costs = [sale.supplier_cost, sale.shipping_cost, sale.ebay_fees];
  if (costs.some((value) => value === null)) return "-";
  return formatGBP(
    (costs[0] as number) + (costs[1] as number) + (costs[2] as number)
  );
}

/**
 * Phase I — the user's own sales records.
 *
 * Entry and import live here rather than on the dashboard. Every row is
 * labelled user-declared, a missing cost is refused rather than stored as
 * zero, and the threshold panel only replays scores already in the database.
 * It has no control that could change a C14 threshold.
 */
export default function SalesPage() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  // Start empty and set the local date after mount: the server's calendar is
  // not necessarily the browser's at midnight, and that would hydrate a
  // different date into the input.
  const [form, setForm] = useState<SaleFormValues>(EMPTY_SALE_FORM);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<SalesCsvImportResult | null>(
    null
  );
  const [confirmSale, setConfirmSale] = useState<Sale | null>(null);

  const [verified, setVerified] = useState("0.65");
  const [unverified, setUnverified] = useState("0.45");
  const [replay, setReplay] = useState<ThresholdReplay | null>(null);
  const [replayLoading, setReplayLoading] = useState(true);
  const [replayError, setReplayError] = useState<string | null>(null);

  async function loadSales() {
    setLoading(true);
    try {
      const response = await fetchSales(500);
      setSales(response.sales || []);
      setCount(response.count);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sales");
    } finally {
      setLoading(false);
    }
  }

  async function loadReplay(nextVerified?: string, nextUnverified?: string) {
    const hasProposal =
      nextVerified !== undefined && nextUnverified !== undefined;
    setReplayLoading(true);
    setReplayError(null);
    try {
      // The first load asks with no thresholds, so the backend supplies its
      // current C14 constants. A user-requested replay sends the typed pair.
      const report = hasProposal
        ? await replayThresholds(Number(nextVerified), Number(nextUnverified))
        : await replayThresholds();
      setReplay(report);
      if (!hasProposal) {
        setVerified(String(report.current.verified));
        setUnverified(String(report.current.unverified));
      }
    } catch (err) {
      setReplayError(
        err instanceof Error ? err.message : "Failed to replay thresholds"
      );
    } finally {
      setReplayLoading(false);
    }
  }

  useEffect(() => {
    setForm(initialForm());
    loadSales();
    loadReplay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateForm<Key extends keyof SaleFormValues>(
    key: Key,
    value: SaleFormValues[Key]
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submitSale(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const built = buildSaleRequest(form);
    if (!built.ok) {
      setError(built.error);
      setNotice(null);
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await createSale(built.payload);
      setForm(initialForm());
      setNotice(
        "Sale recorded. Revenue, profit and the affected month were recomputed from your declared values."
      );
      await loadSales();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save the sale");
    } finally {
      setSaving(false);
    }
  }

  async function submitImport() {
    if (!csvFile || importing) return;
    setImporting(true);
    setError(null);
    setNotice(null);
    setImportResult(null);
    try {
      const text = await csvFile.text();
      const result = await importSalesCsv(text, csvFile.name);
      setImportResult(result);
      await loadSales();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import the CSV");
    } finally {
      setImporting(false);
    }
  }

  async function removeSale() {
    if (!confirmSale) return;
    const target = confirmSale;
    setConfirmSale(null);
    try {
      await deleteSale(target.id);
      setNotice(`Deleted “${target.product_name}”. The month was recomputed.`);
      await loadSales();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete the sale"
      );
    }
  }

  function downloadTemplate() {
    const blob = new Blob([salesCsvTemplate()], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "sales_template.csv";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function submitReplay(event: FormEvent) {
    event.preventDefault();
    const v = Number(verified);
    const u = Number(unverified);
    if (
      verified.trim() === "" ||
      unverified.trim() === "" ||
      !Number.isFinite(v) ||
      !Number.isFinite(u) ||
      v < 0 ||
      v > 1 ||
      u < 0 ||
      u > 1
    ) {
      setReplayError("Both thresholds must be numbers between 0 and 1.");
      return;
    }
    if (u > v) {
      setReplayError(
        "The shown threshold cannot be higher than the confirmed threshold."
      );
      return;
    }
    loadReplay(verified, unverified);
  }

  const saleColumns: Column<Sale>[] = [
    {
      key: "date",
      header: "Date",
      render: (sale) => formatSaleDate(sale.sale_date),
      sortValue: (sale) => sale.sale_date || "",
    },
    {
      key: "product",
      header: "Product",
      render: (sale) => (
        <span
          className="block max-w-[220px] truncate"
          title={sale.product_name}
        >
          {sale.product_name}
        </span>
      ),
      sortValue: (sale) => sale.product_name,
    },
    {
      key: "qty",
      header: "Qty",
      align: "right",
      render: (sale) => sale.quantity,
      sortValue: (sale) => sale.quantity,
    },
    {
      key: "sale",
      header: "Unit sale",
      align: "right",
      render: (sale) => formatGBP(sale.sale_price),
      sortValue: (sale) => sale.sale_price,
    },
    {
      key: "costs",
      header: "Unit costs",
      align: "right",
      render: (sale) => (
        <span title="Supplier + shipping + eBay fees, per unit">
          {costCell(sale)}
        </span>
      ),
      sortValue: (sale) =>
        sale.supplier_cost === null ||
        sale.shipping_cost === null ||
        sale.ebay_fees === null
          ? -1
          : (sale.supplier_cost || 0) +
            (sale.shipping_cost || 0) +
            (sale.ebay_fees || 0),
    },
    {
      key: "profit",
      header: "Profit (total)",
      align: "right",
      render: (sale) => (
        <span
          className={sale.profit === null ? "text-text-dim" : "text-brand-lime"}
          title={sale.profit_missing_reason || undefined}
        >
          {formatGBP(sale.profit)}
        </span>
      ),
      sortValue: (sale) => sale.profit ?? Number.NEGATIVE_INFINITY,
    },
    {
      key: "margin",
      header: "Margin",
      align: "right",
      render: (sale) => formatPercent(sale.margin_percent),
      sortValue: (sale) => sale.margin_percent ?? Number.NEGATIVE_INFINITY,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (sale) => (
        <button
          type="button"
          onClick={() => setConfirmSale(sale)}
          className="text-xs font-semibold text-accent-red hover:underline"
        >
          Delete
        </button>
      ),
    },
  ];

  const differenceColumns: Column<ThresholdDifferenceRow>[] = [
    {
      key: "product",
      header: "eBay product",
      render: (row) => (
        <span
          className="block max-w-[220px] truncate"
          title={row.product_title || ""}
        >
          {row.product_title || "Product title not stored"}
        </span>
      ),
    },
    {
      key: "supplier",
      header: "Supplier row",
      render: (row) => (
        <span
          className="block max-w-[180px] truncate"
          title={row.supplier_title || ""}
        >
          {row.supplier_title || row.supplier_name || "-"}
        </span>
      ),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      render: (row) => row.match_score.toFixed(4),
      sortValue: (row) => row.match_score,
    },
    {
      key: "change",
      header: "Change",
      render: (row) => (
        <span className="text-xs">
          {changeLabel(row.change)}
          <span className="block text-text-dim">
            {tierLabel(row.current_tier)} → {tierLabel(row.proposed_tier)}
          </span>
        </span>
      ),
    },
    {
      key: "verdict",
      header: "Stored verdict",
      render: (row) => (
        <span className="capitalize">{row.verdict.replaceAll("_", " ")}</span>
      ),
    },
  ];

  const currentConfirmed = replay
    ? replay.outcomes.current_confirmed_by_verdict
    : {};
  const proposedConfirmed = replay
    ? replay.outcomes.proposed_confirmed_by_verdict
    : {};

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-white">Sales</h1>
            <Badge tone="neutral">User-declared</Badge>
          </div>
          <p className="text-sm text-text-dim mt-1 max-w-3xl">
            {SALES_DECLARATION} Profit is calculated only when you declare the
            supplier cost, shipping and eBay fees. A blank cost is refused; a
            real zero must be typed as 0.
          </p>
        </div>
        <Link href="/dashboard" className={BUTTON_LINK}>
          View dashboard
        </Link>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/40 text-accent-red rounded-card px-4 py-3 text-sm">
          {error}
        </div>
      )}
      {notice && (
        <div className="bg-brand-lime/10 border border-brand-lime/40 text-brand-lime rounded-card px-4 py-3 text-sm">
          {notice}
        </div>
      )}

      <div className="grid lg:grid-cols-[1.35fr_1fr] gap-4">
        <Card title="Record a sale">
          <form onSubmit={submitSale} className="space-y-3">
            <div className="grid sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <Label htmlFor="sale-product">Product name</Label>
                <Input
                  id="sale-product"
                  value={form.product_name}
                  onChange={(event) =>
                    updateForm("product_name", event.target.value)
                  }
                  placeholder="e.g. Cordless drill"
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-category">Category (optional)</Label>
                <Input
                  id="sale-category"
                  value={form.category}
                  onChange={(event) =>
                    updateForm("category", event.target.value)
                  }
                  placeholder="Tools"
                />
              </div>
              <div>
                <Label htmlFor="sale-date">Sale date</Label>
                <Input
                  id="sale-date"
                  type="date"
                  value={form.sale_date}
                  onChange={(event) =>
                    updateForm("sale_date", event.target.value)
                  }
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-price">Sale price (per unit)</Label>
                <Input
                  id="sale-price"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={form.sale_price}
                  onChange={(event) =>
                    updateForm("sale_price", event.target.value)
                  }
                  placeholder="0.00"
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-qty">Quantity</Label>
                <Input
                  id="sale-qty"
                  type="number"
                  min="1"
                  step="1"
                  value={form.quantity}
                  onChange={(event) =>
                    updateForm("quantity", event.target.value)
                  }
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-cost">Supplier cost (per unit)</Label>
                <Input
                  id="sale-cost"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.supplier_cost}
                  onChange={(event) =>
                    updateForm("supplier_cost", event.target.value)
                  }
                  placeholder="0.00"
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-shipping">Shipping cost (per unit)</Label>
                <Input
                  id="sale-shipping"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.shipping_cost}
                  onChange={(event) =>
                    updateForm("shipping_cost", event.target.value)
                  }
                  placeholder="0.00"
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-fees">eBay fees (per unit)</Label>
                <Input
                  id="sale-fees"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.ebay_fees}
                  onChange={(event) =>
                    updateForm("ebay_fees", event.target.value)
                  }
                  placeholder="0.00"
                  required
                />
              </div>
              <div>
                <Label htmlFor="sale-buyer">Buyer location (optional)</Label>
                <Input
                  id="sale-buyer"
                  value={form.buyer_location}
                  onChange={(event) =>
                    updateForm("buyer_location", event.target.value)
                  }
                  placeholder="UK"
                />
              </div>
              <div className="sm:col-span-2">
                <Label htmlFor="sale-notes">Notes (optional)</Label>
                <Textarea
                  id="sale-notes"
                  value={form.notes}
                  onChange={(event) => updateForm("notes", event.target.value)}
                  placeholder="Anything you want to remember about this sale."
                />
              </div>
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-text-dim">
                Costs are per unit and are multiplied by quantity.
              </p>
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Record sale"}
              </Button>
            </div>
          </form>
        </Card>

        <Card
          title="Import a CSV"
          action={
            <button
              type="button"
              onClick={downloadTemplate}
              className="text-xs font-semibold text-brand-lime hover:underline"
            >
              Download template
            </button>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-text-secondary">
              Every row needs a product name, sale price, all three costs,
              quantity and sale date. Imported profit and margin columns are
              ignored and recomputed from those values.
            </p>
            <Input
              type="file"
              accept=".csv,text/csv"
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                setCsvFile(event.target.files?.[0] || null);
                setImportResult(null);
              }}
            />
            <p className="text-xs text-text-dim break-words">
              Required headers:{" "}
              {SALES_CSV_HEADERS.split(",").slice(0, 7).join(", ")}.
              Export-shaped headers such as “Sale Price”, “Cost”, “Fees” and
              “Qty” are also accepted.
            </p>
            <Button
              type="button"
              onClick={submitImport}
              disabled={!csvFile || importing}
            >
              {importing ? "Importing…" : "Import CSV"}
            </Button>

            {importResult && (
              <div className="border border-border rounded-card p-3 space-y-2">
                <div className="text-sm text-white font-semibold">
                  {importResult.rows_imported} imported,{" "}
                  {importResult.rows_rejected} rejected
                </div>
                <div className="text-xs text-text-dim">
                  {importResult.rows_received} data row
                  {importResult.rows_received === 1 ? "" : "s"} read;{" "}
                  {importResult.months_recomputed} month
                  {importResult.months_recomputed === 1 ? "" : "s"} recomputed.
                </div>
                {importResult.errors.length > 0 && (
                  <ul className="text-xs text-accent-red space-y-1 max-h-40 overflow-y-auto">
                    {importResult.errors.map((row) => (
                      <li key={`${row.line}-${row.reason}`}>
                        Line {row.line}: {row.reason}
                      </li>
                    ))}
                  </ul>
                )}
                {importResult.errors_truncated && (
                  <div className="text-xs text-accent-amber">
                    More errors were found than are listed.
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
      </div>

      <Card
        title="C14 threshold feedback"
        action={<Badge tone="neutral">Read-only</Badge>}
      >
        <p className="text-sm text-text-secondary">
          Replays the supplier-match scores already stored by C14. It reports
          which rows would move at another pair of thresholds and changes
          nothing. It cannot recover rows the matcher never stored.
        </p>

        <form
          onSubmit={submitReplay}
          className="mt-4 flex flex-wrap items-end gap-3"
        >
          <div className="w-32">
            <Label htmlFor="threshold-verified">Confirmed ≥</Label>
            <Input
              id="threshold-verified"
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={verified}
              onChange={(event) => setVerified(event.target.value)}
            />
          </div>
          <div className="w-32">
            <Label htmlFor="threshold-unverified">Shown ≥</Label>
            <Input
              id="threshold-unverified"
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={unverified}
              onChange={(event) => setUnverified(event.target.value)}
            />
          </div>
          <Button type="submit" variant="secondary" disabled={replayLoading}>
            {replayLoading ? "Replaying…" : "Replay stored scores"}
          </Button>
          {replay && (
            <span className="text-xs text-text-dim">
              Current C14: confirmed ≥ {replay.current.verified.toFixed(2)},
              shown ≥ {replay.current.unverified.toFixed(2)}
            </span>
          )}
        </form>

        {replayError && (
          <div className="mt-3 text-sm text-accent-red">{replayError}</div>
        )}

        {replayLoading ? (
          <div className="mt-4">
            <Spinner label="Reading stored matcher scores." />
          </div>
        ) : replay ? (
          <div className="mt-4 space-y-4">
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
              <div className="bg-bg-surface border border-border rounded-card p-3">
                <div className="text-xs text-text-dim uppercase tracking-wide">
                  Stored rows
                </div>
                <div className="font-mono text-lg text-white">
                  {replay.sample.stored_rows}
                </div>
                <div className="text-xs text-text-dim">
                  {replay.sample.scored_rows} scored;{" "}
                  {replay.sample.unscored_rows} without a score
                </div>
              </div>
              <div className="bg-bg-surface border border-border rounded-card p-3">
                <div className="text-xs text-text-dim uppercase tracking-wide">
                  Products
                </div>
                <div className="font-mono text-lg text-white">
                  {replay.sample.products}
                </div>
                <div className="text-xs text-text-dim">
                  {replay.sample.rows_with_a_verdict} rows carry a stored
                  verdict
                </div>
              </div>
              <div className="bg-bg-surface border border-border rounded-card p-3">
                <div className="text-xs text-text-dim uppercase tracking-wide">
                  Current confirmed
                </div>
                <div className="font-mono text-lg text-white">
                  {replay.current_tiers.verified}
                </div>
                <div className="text-xs text-text-dim">
                  {replay.current_tiers.unverified} shown as not confirmed
                </div>
              </div>
              <div className="bg-bg-surface border border-border rounded-card p-3">
                <div className="text-xs text-text-dim uppercase tracking-wide">
                  Proposed confirmed
                </div>
                <div className="font-mono text-lg text-white">
                  {replay.proposed_tiers.verified}
                </div>
                <div className="text-xs text-text-dim">
                  {replay.differences.changed} row
                  {replay.differences.changed === 1 ? "" : "s"} change tier
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="pass">
                pass: {currentConfirmed.pass ?? 0} →{" "}
                {proposedConfirmed.pass ?? 0}
              </Badge>
              <Badge tone="fail">
                fail: {currentConfirmed.fail ?? 0} →{" "}
                {proposedConfirmed.fail ?? 0}
              </Badge>
              <Badge tone="pending">
                pending: {currentConfirmed.pending ?? 0} →{" "}
                {proposedConfirmed.pending ?? 0}
              </Badge>
              <Badge tone="neutral">
                no stored verdict: {currentConfirmed.not_recorded ?? 0} →{" "}
                {proposedConfirmed.not_recorded ?? 0}
              </Badge>
            </div>
            <p className="text-xs text-text-dim">
              Verdict figures count confirmed rows and show current → proposed.
            </p>

            {replay.sample.scored_rows === 0 ? (
              <div className="bg-bg-surface border border-border rounded-card px-4 py-3 text-sm text-text-secondary">
                No stored supplier scores to replay. Feedback begins after an
                analysis stores a supplier match with a `match_score`.
              </div>
            ) : replay.differences.changed === 0 ? (
              <div className="bg-bg-surface border border-border rounded-card px-4 py-3 text-sm text-text-secondary">
                No stored row changes tier at these thresholds.
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-sm text-text-secondary">
                  {replay.differences.confirmed_lost} lose confirmation,{" "}
                  {replay.differences.confirmed_gained} gain it,{" "}
                  {replay.differences.shown_lost} disappear from the shown set
                  and {replay.differences.shown_gained} newly appear. These
                  categories can overlap.
                </p>
                <DataTable
                  columns={differenceColumns}
                  rows={replay.differences.rows}
                  keyFn={(row, index) =>
                    `${row.product_id}-${row.supplier_name}-${row.match_score}-${index}`
                  }
                  emptyMessage="No changed rows at these thresholds."
                />
                {replay.differences.truncated && (
                  <p className="text-xs text-accent-amber">
                    The changed-row list is truncated at{" "}
                    {replay.differences.rows.length} rows.
                  </p>
                )}
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-white mb-2">
                Confirmed threshold sweep
              </h3>
              <div className="overflow-x-auto border border-border rounded-card">
                <table className="w-full text-sm min-w-[620px]">
                  <thead>
                    <tr className="bg-bg-surface border-b border-border text-text-dim">
                      <th className="px-3 py-2 text-left text-[11px] uppercase tracking-wide">
                        Confirmed ≥
                      </th>
                      <th className="px-3 py-2 text-right text-[11px] uppercase tracking-wide">
                        Confirmed rows
                      </th>
                      <th className="px-3 py-2 text-right text-[11px] uppercase tracking-wide">
                        Lost vs current
                      </th>
                      <th className="px-3 py-2 text-right text-[11px] uppercase tracking-wide">
                        On passed products
                      </th>
                      <th className="px-3 py-2 text-right text-[11px] uppercase tracking-wide">
                        On failed products
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {replay.sweep.map((row: ThresholdSweepRow) => {
                      const current =
                        row.verified_threshold === replay.current.verified;
                      return (
                        <tr
                          key={row.verified_threshold}
                          className={
                            current
                              ? "bg-brand-lime/10 border-b border-border"
                              : "border-b border-border last:border-0"
                          }
                        >
                          <td className="px-3 py-2 font-mono text-white">
                            {row.verified_threshold.toFixed(2)}
                            {current && (
                              <span className="ml-2 text-[10px] uppercase text-brand-lime">
                                current
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-white">
                            {row.confirmed}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-accent-amber">
                            {row.confirmed_lost_vs_current}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-brand-lime">
                            {row.confirmed_pass}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-accent-red">
                            {row.confirmed_fail}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <p className="text-xs text-text-dim">{replay.note}</p>
            <p className="text-xs text-accent-amber">{replay.limitation}</p>
          </div>
        ) : null}
      </Card>

      <Card
        title={`Sale log (${count})`}
        action={<Badge tone="neutral">User-declared</Badge>}
      >
        {loading ? (
          <Spinner label="Loading sales." />
        ) : (
          <>
            <DataTable
              columns={saleColumns}
              rows={sales}
              keyFn={(sale) => sale.id}
              emptyMessage="No sales recorded yet. Use the form above or import a CSV."
            />
            {count > sales.length && (
              <p className="text-xs text-text-dim mt-2">
                Showing the newest {sales.length} of {count} sales.
              </p>
            )}
          </>
        )}
      </Card>

      <ConfirmDialog
        open={confirmSale !== null}
        title="Delete this sale?"
        message={
          confirmSale
            ? `“${confirmSale.product_name}” on ${formatSaleDate(confirmSale.sale_date)} will be removed, and its month will be recomputed from the remaining sales.`
            : ""
        }
        onConfirm={removeSale}
        onCancel={() => setConfirmSale(null)}
      />
    </div>
  );
}
