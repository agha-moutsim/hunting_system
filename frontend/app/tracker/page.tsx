"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input, { Label } from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import RangeFilterBar from "@/components/ui/RangeFilterBar";
import OutsideBandBadge from "@/components/ui/OutsideBandBadge";
import { apiFetch, apiPost, apiDelete } from "@/lib/api";
import {
  TrackedProduct,
  PriceAlert,
  PriceHistoryPoint,
  PriceTrend,
  PriceRange,
  TrackerListResponse,
} from "@/lib/types";
import { formatGBP, formatSigned, formatDateTime } from "@/lib/format";

export default function TrackerPage() {
  const [products, setProducts] = useState<TrackedProduct[]>([]);
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [viewMin, setViewMin] = useState("");
  const [viewMax, setViewMax] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [rangeFilter, setRangeFilter] = useState<PriceRange | null>(null);
  const [history, setHistory] = useState<{
    product: TrackedProduct;
    points: PriceHistoryPoint[];
    trend: PriceTrend;
  } | null>(null);

  // Add form
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [ebayPrice, setEbayPrice] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [supplierPrice, setSupplierPrice] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const qs =
        viewMin && viewMax
          ? `?price_min=${encodeURIComponent(viewMin)}&price_max=${encodeURIComponent(viewMax)}`
          : "";
      const [p, a] = await Promise.all([
        apiFetch<TrackerListResponse>(`/api/tracker${qs}`),
        apiFetch<{ alerts: PriceAlert[] }>("/api/tracker/alerts?limit=20"),
      ]);
      setProducts(p.products || []);
      setAlerts(a.alerts || []);
      setRangeFilter(p.range_filter || null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tracker");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMin, viewMax, reloadKey]);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      await apiPost("/api/tracker", {
        product_name: name.trim(),
        ebay_url: url.trim(),
        ebay_price: parseFloat(ebayPrice) || 0,
        target_price: parseFloat(targetPrice) || 0,
        supplier_price: parseFloat(supplierPrice) || 0,
        supplier_url: "",
        supplier_name: "",
      });
      setName("");
      setUrl("");
      setEbayPrice("");
      setTargetPrice("");
      setSupplierPrice("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Add failed");
    } finally {
      setSaving(false);
    }
  }

  async function checkPrice(id: number) {
    setCheckingId(id);
    try {
      await apiPost(`/api/tracker/${id}/check`, {});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Check failed");
    } finally {
      setCheckingId(null);
    }
  }

  async function remove() {
    if (confirmId == null) return;
    try {
      await apiDelete(`/api/tracker/${confirmId}`);
      setConfirmId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function showHistory(p: TrackedProduct) {
    try {
      const data = await apiFetch<{
        history: PriceHistoryPoint[];
        trend: PriceTrend;
      }>(`/api/tracker/${p.id}/history?days=30`);
      setHistory({ product: p, points: data.history || [], trend: data.trend });
    } catch {
      setError("Could not load price history");
    }
  }

  const columns: Column<TrackedProduct>[] = [
    {
      key: "name",
      header: "Product",
      render: (r) => (
        <div>
          <div className="font-medium text-text-primary line-clamp-1">
            {r.product_name}
          </div>
          {r.ebay_url && (
            <a
              href={r.ebay_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-accent-blue hover:underline"
            >
              View on eBay
            </a>
          )}
        </div>
      ),
      sortValue: (r) => r.product_name,
    },
    {
      key: "ebay",
      header: "eBay",
      align: "right",
      render: (r) => (
        <span className="inline-flex items-center justify-end gap-1.5">
          {formatGBP(r.ebay_price)}
          {r.outside_band && <OutsideBandBadge />}
        </span>
      ),
      sortValue: (r) => r.ebay_price,
    },
    {
      key: "target",
      header: "Target",
      align: "right",
      render: (r) => formatGBP(r.target_price),
      sortValue: (r) => r.target_price,
    },
    {
      key: "supplier",
      header: "Supplier",
      align: "right",
      render: (r) => formatGBP(r.supplier_price),
      sortValue: (r) => r.supplier_price,
    },
    {
      key: "checked",
      header: "Last checked",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {formatDateTime(r.last_checked)}
        </span>
      ),
      sortValue: (r) => r.last_checked || "",
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <div className="flex justify-end gap-2">
          <Button
            variant="secondary"
            className="px-2! py-1! text-xs"
            onClick={() => checkPrice(r.id)}
            disabled={checkingId === r.id}
          >
            {checkingId === r.id ? "…" : "Check"}
          </Button>
          <Button
            variant="ghost"
            className="px-2! py-1! text-xs"
            onClick={() => showHistory(r)}
          >
            History
          </Button>
          <Button
            variant="danger"
            className="px-2! py-1! text-xs"
            onClick={() => setConfirmId(r.id)}
          >
            Delete
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">Price Tracker</h1>
        <p className="text-sm text-text-secondary mt-1">
          Track eBay + supplier prices and get alerts when they move
        </p>
      </div>

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {/* Alerts */}
      {alerts.length > 0 && (
        <Card title={`Price Alerts (${alerts.length})`}>
          <div className="space-y-2">
            {alerts.map((a) => (
              <div
                key={a.id}
                className="flex flex-wrap items-center gap-2 text-sm bg-bg-surface border border-border rounded-lg px-3 py-2"
              >
                <Badge tone={a.is_read ? "neutral" : "warn"}>
                  {a.is_read ? "read" : "new"}
                </Badge>
                <span className="text-text-primary font-medium">
                  {a.product_name}
                </span>
                <span className="text-text-secondary">
                  {a.message} ({formatGBP(a.old_price)} →{" "}
                  {formatGBP(a.new_price)})
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Add form */}
      <Card title="Add product to track">
        <form
          onSubmit={add}
          className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3"
        >
          <div className="lg:col-span-2">
            <Label>Product name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Product name"
              required
            />
          </div>
          <div>
            <Label>eBay URL (optional)</Label>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
            />
          </div>
          <div>
            <Label>eBay price</Label>
            <Input
              type="number"
              step="0.01"
              value={ebayPrice}
              onChange={(e) => setEbayPrice(e.target.value)}
              placeholder="19.99"
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={saving} className="w-full">
              {saving ? "Adding…" : "Add"}
            </Button>
          </div>
          <div>
            <Label>Target price</Label>
            <Input
              type="number"
              step="0.01"
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
              placeholder="14.99"
            />
          </div>
          <div>
            <Label>Supplier price</Label>
            <Input
              type="number"
              step="0.01"
              value={supplierPrice}
              onChange={(e) => setSupplierPrice(e.target.value)}
              placeholder="6.50"
            />
          </div>
        </form>
      </Card>

      {/* History detail */}
      {history && (
        <Card
          title={`Price history — ${history.product.product_name}`}
          action={
            <Button variant="ghost" onClick={() => setHistory(null)}>
              Close
            </Button>
          }
        >
          <div className="flex gap-4 mb-3 text-sm">
            <span className="text-text-secondary">
              Trend:{" "}
              <Badge
                tone={
                  history.trend.trend === "down"
                    ? "pass"
                    : history.trend.trend === "up"
                      ? "warn"
                      : "neutral"
                }
              >
                {history.trend.trend} (
                {formatSigned(history.trend.change_percent)})
              </Badge>
            </span>
          </div>
          {history.points.length === 0 ? (
            <EmptyState
              icon="📉"
              title="No price points yet"
              message="Click Check on the product to record its first price point."
            />
          ) : (
            <div className="space-y-2">
              {history.points.map((p, i) => (
                <div
                  key={i}
                  className="flex justify-between text-sm bg-bg-surface border border-border rounded-lg px-3 py-2"
                >
                  <span className="text-text-secondary">
                    {formatDateTime(p.checked_at)}
                  </span>
                  <span>
                    eBay {formatGBP(p.ebay_price)}{" "}
                    {p.outside_band && <OutsideBandBadge />} · Supplier{" "}
                    {formatGBP(p.supplier_price)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* View price filter */}
      <RangeFilterBar
        initial={rangeFilter}
        loading={loading}
        onApply={(lo, hi) => {
          setViewMin(String(lo));
          setViewMax(String(hi));
          setReloadKey((k) => k + 1);
        }}
        onReset={() => {
          setViewMin("");
          setViewMax("");
          setReloadKey((k) => k + 1);
        }}
      />

      {/* List */}
      {loading ? (
        <Card>
          <Spinner label="Loading tracker…" />
          <div className="mt-4 space-y-2" aria-hidden>
            <div className="skeleton h-12 rounded-lg" />
            <div className="skeleton h-12 rounded-lg" />
          </div>
        </Card>
      ) : products.length === 0 ? (
        <Card>
          <EmptyState
            icon="📈"
            title="No products tracked yet"
            message="Add a product above to start tracking its eBay and supplier prices."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={products}
          keyFn={(r) => r.id}
          emptyMessage="No tracked products."
        />
      )}

      <ConfirmDialog
        open={confirmId != null}
        title="Remove tracked product?"
        message="This will delete the product and its price history. This cannot be undone."
        onConfirm={remove}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
