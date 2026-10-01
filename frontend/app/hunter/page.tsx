"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import DataTable, { Column } from "@/components/DataTable";
import HotBadge, { hasRealProfit } from "@/components/ui/HotBadge";
import {
  DemandCell,
  HunterEmptyState,
  ProfitCell,
  SupplierCell,
} from "@/components/HunterEmptyState";
import { apiFetch, apiPost } from "@/lib/api";
import {
  CategoryProduct,
  HunterCategory,
  FiltersResponse,
  HunterScanResponse,
  HunterReport,
  PriceRange,
} from "@/lib/types";
import { formatGBP, formatPercent } from "@/lib/format";

export default function HunterPage() {
  const [category, setCategory] = useState("");
  const [maxResults, setMaxResults] = useState("30");
  const [scanLoading, setScanLoading] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<HunterScanResponse | null>(null);
  const [report, setReport] = useState<HunterReport | null>(null);
  const [activeRange, setActiveRange] = useState<PriceRange | null>(null);
  // REGRESSION-001: the old placeholder said "e.g. Garden Tools, Kitchen",
  // and every one of those missed the backend's category table and silently
  // became Electronics. The real category list is fetched and offered as a
  // picker, and anything typed is searched as typed.
  const [categories, setCategories] = useState<HunterCategory[]>([]);

  useEffect(() => {
    apiFetch<FiltersResponse>("/api/filters")
      .then((d) => setActiveRange(d.range))
      .catch(() => setActiveRange(null));
  }, []);

  useEffect(() => {
    apiFetch<{ categories: HunterCategory[] }>("/api/hunter/categories")
      .then((d) => setCategories(d.categories || []))
      .catch(() => setCategories([]));
  }, []);

  const priceMin = activeRange?.min ?? 5;
  const priceMax = activeRange?.max ?? 35;

  async function runScan(e: FormEvent) {
    e.preventDefault();
    if (!category.trim() || scanLoading) return;
    setScanLoading(true);
    setLookupLoading(false);
    setError(null);
    setScan(null);
    setReport(null);
    try {
      const data = await apiPost<HunterScanResponse>("/api/hunter/scan", {
        category: category.trim(),
        // Omitted when the active range failed to load — the server then
        // resolves the scan to the persisted active range (PR-7).
        price_min: activeRange?.min,
        price_max: activeRange?.max,
        max_results: parseInt(maxResults) || 30,
      });
      setScan(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanLoading(false);
    }
  }

  async function runLookup() {
    if (!scan?.products?.length || lookupLoading) return;
    setLookupLoading(true);
    setError(null);
    try {
      const products = scan.products.map((p) => ({
        ...p,
        _total_scanned: scan.total_scanned,
        _price_min: activeRange?.min,
        _price_max: activeRange?.max,
        category,
      }));
      const data = await apiPost<HunterReport>("/api/hunter/lookup", {
        products,
        filters: { price_min: activeRange?.min, price_max: activeRange?.max },
      });
      setReport(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Supplier lookup failed");
    } finally {
      setLookupLoading(false);
    }
  }

  const products = report?.products || scan?.products || [];

  const columns: Column<CategoryProduct>[] = [
    {
      key: "title",
      header: "Product",
      render: (r) => (
        <a
          href={r.url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent-blue hover:underline line-clamp-2"
        >
          {r.title}
        </a>
      ),
      sortValue: (r) => r.title,
    },
    {
      key: "price",
      header: "eBay",
      align: "right",
      render: (r) => formatGBP(r.price),
      sortValue: (r) => r.price,
    },
    {
      key: "hot",
      header: "Trend",
      render: (r) => (
        <HotBadge
          hot={r.hot}
          basis={r.hot_basis}
          provenance={r.hot_provenance}
          reason={r.hot_reason}
        />
      ),
      sortValue: (r) => (r.hot ? 1 : 0),
    },
    {
      key: "sold",
      header: "Sold 30d",
      align: "right",
      render: (r) =>
        r.sold_30d != null ? (
          <DemandCell row={r} />
        ) : (
          <span className="text-text-dim">⚠️</span>
        ),
      sortValue: (r) => r.sold_30d ?? -1,
    },
    {
      key: "supplier",
      header: "Supplier",
      render: (r) => <SupplierCell row={r} report={!!report} />,
      sortValue: (r) => r.supplier_price ?? -1,
    },
    {
      key: "profit",
      header: "Profit",
      align: "right",
      // REGRESSION-005: a row with no supplier has profit 0 and provenance
      // "unverified" - that is the ABSENCE of a calculation, so it renders as
      // a dash with the reason rather than a confident red GBP0.00.
      render: (r) => <ProfitCell row={r} />,
      sortValue: (r) => (hasRealProfit(r) ? (r.profit as number) : -1),
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (r) =>
        r.verdict ? (
          <Badge tone={r.verdict.toLowerCase()}>
            {r.verdict.toUpperCase()}
          </Badge>
        ) : (
          <span className="text-text-dim">—</span>
        ),
      sortValue: (r) => r.verdict || "",
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">Category Hunter</h1>
        <p className="text-sm text-text-secondary mt-1">
          Scan an eBay category, check demand, then find suppliers + profit
        </p>
      </div>

      <Card>
        <form onSubmit={runScan} className="space-y-3">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="sm:col-span-2">
              <label className="block text-xs text-text-secondary mb-1">
                Search a category, or type any product
              </label>
              <Input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                // The old placeholder suggested "Garden Tools, Kitchen",
                // which are NOT categories - the backend silently searched
                // Electronics instead. The real names are listed below.
                placeholder="e.g. cordless drill, garden tools, laptop stand"
                list="hunter-categories"
                disabled={scanLoading || lookupLoading}
              />
              <datalist id="hunter-categories">
                {categories.map((c) => (
                  <option key={c.category_id} value={c.label} />
                ))}
              </datalist>
              <p className="text-xs text-text-dim mt-1">
                Pick one of the {categories.length} categories to browse it, or
                type your own words and we search eBay for exactly those.
              </p>
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">
                Price min
              </label>
              <Input
                type="number"
                value={priceMin}
                disabled
                readOnly
                title="From your active price range (edit it on Analyze or Deep Search)"
                className="font-mono tabular-nums"
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">
                Price max
              </label>
              <Input
                type="number"
                value={priceMax}
                disabled
                readOnly
                title="From your active price range (edit it on Analyze or Deep Search)"
                className="font-mono tabular-nums"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-3 items-center">
            <Button type="submit" disabled={scanLoading || !category.trim()}>
              {scanLoading ? "Scanning…" : "1. Scan Category"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={runLookup}
              disabled={!scan?.products?.length || lookupLoading || scanLoading}
            >
              {lookupLoading
                ? "Looking up suppliers…"
                : `2. Supplier Lookup (${scan?.products.length || 0})`}
            </Button>
            <span className="text-xs text-text-dim">
              max {maxResults} results
            </span>
          </div>
        </form>
      </Card>

      {(scanLoading || lookupLoading) && (
        <Card>
          <div className="py-6">
            <Spinner
              label={
                scanLoading
                  ? "Scanning category + demand check…"
                  : "Supplier lookup + profit calc (can take a minute)…"
              }
            />
            <div className="mt-4 space-y-2" aria-hidden>
              <div className="skeleton h-12 rounded-lg" />
              <div className="skeleton h-12 rounded-lg" />
              <div className="skeleton h-12 rounded-lg" />
            </div>
          </div>
        </Card>
      )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {report && (
        <Card>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { label: "Category", value: report.category || category },
              { label: "Scanned", value: report.total_scanned },
              { label: "With demand", value: report.total_with_demand },
              { label: "With supplier", value: report.total_with_supplier },
              {
                label: "PASS",
                value: (
                  <span className="text-accent-green">{report.total_pass}</span>
                ),
              },
            ].map((m) => (
              <div
                key={m.label}
                className="bg-bg-surface border border-border rounded-lg p-3"
              >
                <div className="text-xs text-text-secondary mb-1">
                  {m.label}
                </div>
                <div className="text-lg font-bold text-text-primary">
                  {m.value}
                </div>
              </div>
            ))}
          </div>
          {report.notes && (
            <p className="text-xs text-accent-amber mt-3">{report.notes}</p>
          )}
        </Card>
      )}

      {(scan || report) && products.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-text-primary">
              Results ({products.length})
              {report?.hot_count ? (
                <span className="ml-2 text-xs font-normal text-text-secondary">
                  {report.hot_count} trending
                </span>
              ) : null}
            </h3>
            {scan && !report && (
              <span className="text-xs text-text-dim">
                Run supplier lookup for profit + verdict
              </span>
            )}
          </div>
          {/* State what was really searched — a keyword search and a category
              browse are different questions, and the user should know which
              one they got (REGRESSION-001). */}
          {(scan?.search || report) && (
            <p className="text-xs text-text-secondary mb-2">
              {scan?.search
                ? scan.search.mode === "category"
                  ? `Browsing the ${scan.search.label} category.`
                  : `Searching eBay for "${scan.search.text}".`
                : null}
            </p>
          )}
          {/* TODO(P5 / C11): surface competitor eBay stores here — the
              endpoints return `ebay_stores` and stamp them, but no per-row
              expansion exists yet to show them. */}
          <DataTable
            columns={columns}
            rows={products}
            keyFn={(r, i) => r.url || i}
            emptyMessage="No products found."
          />
        </div>
      )}

      {(scan || report) &&
        products.length === 0 &&
        !scanLoading &&
        !lookupLoading && (
          <HunterEmptyState
            searchText={scan?.search?.text || category.trim() || undefined}
            mode={scan?.search?.mode}
            summary={report?.summary}
          />
        )}

      {!scanLoading && !lookupLoading && !scan && !error && (
        <Card>
          <div className="text-center py-8 text-sm text-text-dim">
            Enter a category and price range to start hunting.
          </div>
        </Card>
      )}
    </div>
  );
}
