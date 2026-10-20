"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Select from "@/components/ui/Select";
import DataTable, { Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import KpiCard from "@/components/KpiCard";
import Spinner from "@/components/Spinner";
import { RevenueProfitChart } from "@/components/charts";
import { downloadFile } from "@/lib/api";
import { formatGBP, formatPercent, formatSigned } from "@/lib/format";
import {
  SALES_DECLARATION,
  fetchSales,
  fetchSalesSummary,
  formatSaleDate,
  monthlyChartData,
} from "@/lib/sales";
import type { Sale, SalesSummary } from "@/lib/types";

const BUTTON_LINK =
  "inline-flex items-center justify-center px-4 py-2 rounded-control text-sm font-semibold bg-accent-blue text-white hover:bg-accent-blue-dark transition-colors duration-150";

/**
 * Phase I — the dashboard is a P&L over the user's own records, not a claim
 * about eBay. Revenue, profit and margin come from `/api/sales/summary`; every
 * value carries the user-declared label, and an unknown profit stays absent
 * instead of becoming a zero. The monthly bars use the same summary rows.
 */
export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<SalesSummary | null>(null);
  const [sales, setSales] = useState<Sale[]>([]);
  const [salesCount, setSalesCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [nextSummary, list] = await Promise.all([
        fetchSalesSummary(days, 6),
        fetchSales(100),
      ]);
      setSummary(nextSummary);
      setSales(list.sales || []);
      setSalesCount(list.count);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  async function exportFile(path: string, filename: string) {
    try {
      await downloadFile(path, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    }
  }

  const chart = summary ? monthlyChartData(summary) : null;
  const noSalesInPeriod = summary !== null && summary.total_sales === 0;
  const hasAnySales = sales.length > 0;

  const recentColumns: Column<Sale>[] = [
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
          className="block max-w-[260px] truncate"
          title={sale.product_name}
        >
          {sale.product_name}
        </span>
      ),
      sortValue: (sale) => sale.product_name,
    },
    {
      key: "price",
      header: "Unit price",
      align: "right",
      render: (sale) => (
        <span>
          {formatGBP(sale.sale_price)}
          {sale.quantity !== 1 && (
            <span className="text-text-dim"> × {sale.quantity}</span>
          )}
        </span>
      ),
      sortValue: (sale) => sale.sale_price,
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
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <Badge tone="neutral">User-declared</Badge>
          </div>
          <p className="text-sm text-text-dim mt-1 max-w-2xl">
            {SALES_DECLARATION} The C14 threshold report is on the sales page.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-40">
            <Select
              aria-label="Reporting period"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </Select>
          </div>
          <Button
            variant="secondary"
            onClick={() => exportFile("/api/export/csv", "sales_history.csv")}
          >
            Export CSV
          </Button>
          <Link href="/sales" className={BUTTON_LINK}>
            Record or import
          </Link>
        </div>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/40 text-accent-red rounded-card px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <Card>
          <Spinner label="Loading dashboard." />
          <div
            className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4"
            aria-hidden
          >
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
          </div>
          <div className="skeleton h-64 rounded-xl mt-4" aria-hidden />
        </Card>
      ) : noSalesInPeriod ? (
        <Card>
          <EmptyState
            icon="£"
            title={
              hasAnySales
                ? "No user-declared sales in this period"
                : "No user-declared sales yet"
            }
            message={
              hasAnySales
                ? `You have ${salesCount} recorded sale${salesCount === 1 ? "" : "s"} outside the last ${days} days. Choose a longer period, or add another sale.`
                : "Record a sale or import a CSV. Revenue and profit appear here only after you have entered the costs; nothing is estimated."
            }
            action={
              <Link href="/sales" className={BUTTON_LINK}>
                Record or import sales
              </Link>
            }
          />
        </Card>
      ) : (
        summary && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <KpiCard
                label={`Revenue (${days}d)`}
                value={formatGBP(summary.total_revenue)}
                delta={
                  summary.growth_revenue != null
                    ? `${formatSigned(summary.growth_revenue)} vs prev`
                    : undefined
                }
                deltaGood={
                  summary.growth_revenue != null
                    ? summary.growth_revenue >= 0
                    : undefined
                }
              />
              <KpiCard
                label={`Profit (${days}d)`}
                value={formatGBP(summary.total_profit)}
                delta={
                  summary.growth_profit != null
                    ? `${formatSigned(summary.growth_profit)} vs prev`
                    : undefined
                }
                deltaGood={
                  summary.growth_profit != null
                    ? summary.growth_profit >= 0
                    : undefined
                }
              />
              <KpiCard
                label="Average margin"
                value={formatPercent(summary.avg_margin)}
              />
              <KpiCard
                label="Sales"
                value={String(summary.total_sales)}
                delta={`${summary.total_units} unit${
                  summary.total_units === 1 ? "" : "s"
                }`}
              />
            </div>

            {summary.profit_missing_reason && (
              <div className="bg-accent-amber/10 border border-accent-amber/40 text-accent-amber rounded-card px-4 py-3 text-sm">
                {summary.profit_missing_reason}
              </div>
            )}

            <Card
              title={`Revenue vs profit (${summary.monthly_window_months} months)`}
              action={<Badge tone="neutral">User-declared</Badge>}
            >
              {chart && (
                <RevenueProfitChart
                  labels={chart.labels}
                  revenue={chart.revenue}
                  profit={chart.profit}
                />
              )}
              <p className="text-xs text-text-dim mt-2">
                Monthly totals are sums of the sales you entered. A month with
                an undeclared cost has no profit bar rather than a zero.
              </p>
            </Card>

            <Card
              title="Recent sales"
              action={
                <Link
                  href="/sales"
                  className="text-xs font-semibold text-brand-lime hover:underline"
                >
                  Manage all {salesCount} →
                </Link>
              }
            >
              <DataTable
                columns={recentColumns}
                rows={sales.slice(0, 8)}
                keyFn={(sale) => sale.id}
                emptyMessage="No sales recorded yet."
              />
            </Card>
          </>
        )
      )}
    </div>
  );
}
