"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input, { Label } from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import ConfirmDialog from "@/components/ConfirmDialog";
import KpiCard from "@/components/KpiCard";
import DataTable, { Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import {
  TrendLine,
  RevenueProfitChart,
  CategoryPie,
} from "@/components/charts";
import { apiFetch, apiPost, apiDelete, downloadFile } from "@/lib/api";
import {
  Kpis,
  TrendChart,
  CategoryBreakdown,
  MonthlyComparison,
  TopItem,
  Sale,
} from "@/lib/types";
import {
  formatGBP,
  formatPercent,
  formatSigned,
  formatDate,
} from "@/lib/format";

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [revenue, setRevenue] = useState<TrendChart | null>(null);
  const [profit, setProfit] = useState<TrendChart | null>(null);
  const [cats, setCats] = useState<CategoryBreakdown | null>(null);
  const [monthly, setMonthly] = useState<MonthlyComparison | null>(null);
  const [topProducts, setTopProducts] = useState<TopItem[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Sale form
  const [fName, setFName] = useState("");
  const [fCat, setFCat] = useState("");
  const [fPrice, setFPrice] = useState("");
  const [fCost, setFCost] = useState("");
  const [fShip, setFShip] = useState("");
  const [fQty, setFQty] = useState("1");
  const [fDate, setFDate] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [k, rev, pro, c, m, tp, s] = await Promise.all([
        apiFetch<Kpis>(`/api/dashboard/kpis?days=${days}`),
        apiFetch<TrendChart>(`/api/dashboard/charts/revenue-trend?days=${days}`),
        apiFetch<TrendChart>(`/api/dashboard/charts/profit-trend?days=${days}`),
        apiFetch<CategoryBreakdown>("/api/dashboard/charts/categories"),
        apiFetch<MonthlyComparison>("/api/dashboard/charts/monthly"),
        apiFetch<{ products: TopItem[] }>("/api/dashboard/top-products?limit=5"),
        apiFetch<{ sales: Sale[] }>("/api/sales?limit=100"),
      ]);
      setKpis(k);
      setRevenue(rev);
      setProfit(pro);
      setCats(c);
      setMonthly(m);
      setTopProducts(tp.products || []);
      setSales(s.sales || []);
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

  async function logSale(e: FormEvent) {
    e.preventDefault();
    if (!fName.trim() || !fPrice || saving) return;
    setSaving(true);
    try {
      await apiPost("/api/sales", {
        product_name: fName.trim(),
        category: fCat.trim(),
        sale_price: parseFloat(fPrice) || 0,
        supplier_cost: parseFloat(fCost) || 0,
        shipping_cost: parseFloat(fShip) || 0,
        ebay_fees: 0,
        quantity: parseInt(fQty) || 1,
        sale_date: fDate || null,
        buyer_location: "",
        notes: "",
      });
      setFName("");
      setFCat("");
      setFPrice("");
      setFCost("");
      setFShip("");
      setFQty("1");
      setFDate("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log sale");
    } finally {
      setSaving(false);
    }
  }

  async function removeSale() {
    if (confirmId == null) return;
    try {
      await apiDelete(`/api/sales/${confirmId}`);
      setConfirmId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const toPoints = (t: TrendChart | null) => {
    if (!t?.dates?.length) return [];
    return t.dates.map((d, i) => ({
      date: d.slice(5),
      value: t.values[i] || 0,
    }));
  };

  const saleCols: Column<Sale>[] = [
    {
      key: "name",
      header: "Product",
      render: (r) => (
        <div>
          <div className="font-medium text-text-primary">{r.product_name}</div>
          <div className="text-xs text-text-dim">{r.category || "—"}</div>
        </div>
      ),
      sortValue: (r) => r.product_name,
    },
    {
      key: "date",
      header: "Date",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {formatDate(r.sale_date)}
        </span>
      ),
      sortValue: (r) => r.sale_date || "",
    },
    {
      key: "price",
      header: "Sale",
      align: "right",
      render: (r) => formatGBP(r.sale_price),
      sortValue: (r) => r.sale_price,
    },
    {
      key: "qty",
      header: "Qty",
      align: "right",
      render: (r) => r.quantity,
      sortValue: (r) => r.quantity,
    },
    {
      key: "profit",
      header: "Profit",
      align: "right",
      render: (r) => (
        <span className={r.profit >= 0 ? "text-accent-green" : "text-accent-red"}>
          {formatGBP(r.profit)} ({formatPercent(r.margin_percent)})
        </span>
      ),
      sortValue: (r) => r.profit,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <Button
          variant="danger"
          className="!px-2 !py-1 text-xs"
          onClick={() => setConfirmId(r.id)}
        >
          Delete
        </Button>
      ),
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Dashboard</h1>
          <p className="text-sm text-text-secondary mt-1">
            Sales KPIs, trends, and sale log
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value))}
            className="bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <Button variant="secondary" onClick={() => downloadFile("/api/export/csv?type=sales", "sales.csv")}>
            Export CSV
          </Button>
          <Button variant="secondary" onClick={() => downloadFile("/api/export/json?type=sales", "sales.json")}>
            Export JSON
          </Button>
          <Button onClick={() => setShowForm(!showForm)}>
            {showForm ? "Hide form" : "+ Log sale"}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {showForm && (
        <Card title="Log a sale">
          <form onSubmit={logSale} className="grid sm:grid-cols-2 lg:grid-cols-6 gap-3">
            <div className="lg:col-span-2">
              <Label>Product name</Label>
              <Input
                value={fName}
                onChange={(e) => setFName(e.target.value)}
                placeholder="Product sold"
                required
              />
            </div>
            <div>
              <Label>Category</Label>
              <Input
                value={fCat}
                onChange={(e) => setFCat(e.target.value)}
                placeholder="Home"
              />
            </div>
            <div>
              <Label>Sale price £</Label>
              <Input
                type="number"
                step="0.01"
                value={fPrice}
                onChange={(e) => setFPrice(e.target.value)}
                required
              />
            </div>
            <div>
              <Label>Cost £</Label>
              <Input
                type="number"
                step="0.01"
                value={fCost}
                onChange={(e) => setFCost(e.target.value)}
              />
            </div>
            <div>
              <Label>Shipping £</Label>
              <Input
                type="number"
                step="0.01"
                value={fShip}
                onChange={(e) => setFShip(e.target.value)}
              />
            </div>
            <div>
              <Label>Qty</Label>
              <Input
                type="number"
                min={1}
                value={fQty}
                onChange={(e) => setFQty(e.target.value)}
              />
            </div>
            <div>
              <Label>Date</Label>
              <Input
                type="date"
                value={fDate}
                onChange={(e) => setFDate(e.target.value)}
              />
            </div>
            <div className="flex items-end lg:col-span-2">
              <Button type="submit" disabled={saving} className="w-full">
                {saving ? "Saving…" : "Log sale"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loading ? (
        <Card>
          <Spinner label="Loading dashboard…" />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4" aria-hidden>
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
            <div className="skeleton h-20 rounded-xl" />
          </div>
          <div className="skeleton h-64 rounded-xl mt-4" aria-hidden />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              label={`Revenue (${days}d)`}
              value={formatGBP(kpis?.total_revenue)}
              delta={
                kpis?.growth_revenue != null
                  ? `${formatSigned(kpis.growth_revenue)} vs prev`
                  : undefined
              }
              deltaGood={
                kpis?.growth_revenue != null ? kpis.growth_revenue >= 0 : undefined
              }
            />
            <KpiCard
              label={`Profit (${days}d)`}
              value={formatGBP(kpis?.total_profit)}
              delta={
                kpis?.growth_profit != null
                  ? `${formatSigned(kpis.growth_profit)} vs prev`
                  : undefined
              }
              deltaGood={
                kpis?.growth_profit != null ? kpis.growth_profit >= 0 : undefined
              }
            />
            <KpiCard
              label="Avg margin"
              value={formatPercent(kpis?.avg_margin)}
            />
            <KpiCard
              label="Sales"
              value={String(kpis?.total_sales ?? 0)}
              delta={`${kpis?.total_units ?? 0} units`}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card title={`Revenue trend (${days}d)`}>
              <TrendLine
                data={toPoints(revenue)}
                color="#3B82F6"
              />
            </Card>
            <Card title={`Profit trend (${days}d)`}>
              <TrendLine
                data={toPoints(profit)}
                color="#10B981"
              />
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card title="Revenue vs profit (monthly)">
              <RevenueProfitChart
                labels={monthly?.labels || []}
                revenue={monthly?.revenue || []}
                profit={monthly?.profit || []}
              />
            </Card>
            <Card title="Revenue by category">
              <CategoryPie
                categories={cats?.categories || []}
                values={cats?.values || []}
              />
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card title="Top products">
              {topProducts.length === 0 ? (
                <EmptyState
                  icon="🏆"
                  title="No products yet"
                  message="Log a sale to see top performers."
                />
              ) : (
                <div className="space-y-2">
                  {topProducts.map((p, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between gap-3 bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm"
                    >
                      <span className="text-text-primary truncate">
                        {i + 1}. {p.product_name}
                      </span>
                      <span className="text-accent-green whitespace-nowrap">
                        {formatGBP(p.total_profit)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <Card title="Quick stats">
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Best product</span>
                  <span className="text-text-primary">
                    {kpis?.best_product || "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Best category</span>
                  <span className="text-text-primary">
                    {kpis?.best_category || "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Period</span>
                  <span className="text-text-primary">Last {days} days</span>
                </div>
                {kpis?.error && (
                  <div className="text-accent-amber text-xs">⚠️ {kpis.error}</div>
                )}
              </div>
            </Card>
          </div>

          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-text-primary">
                Sale log ({sales.length})
              </h3>
            </div>
            <DataTable
              columns={saleCols}
              rows={sales}
              keyFn={(r) => r.id}
              emptyMessage="No sales logged yet — use the form above to log your first sale."
            />
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirmId != null}
        title="Delete this sale?"
        message="The sale will be removed from history and KPIs will update. This cannot be undone."
        onConfirm={removeSale}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
