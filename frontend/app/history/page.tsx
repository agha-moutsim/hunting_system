"use client";

import { useEffect, useState, useCallback } from "react";
import Card from "@/components/ui/Card";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Spinner from "@/components/Spinner";
import DataTable, { Column } from "@/components/DataTable";
import Scorecard from "@/components/Scorecard";
import EmptyState from "@/components/EmptyState";
import { apiFetch } from "@/lib/api";
import { HistoryItem, ProductDetail, ScrapedProduct } from "@/lib/types";
import { formatGBP, formatDate, truncate } from "@/lib/format";

interface HistoryResponse {
  products: HistoryItem[];
  count: number;
}

function parseFilters(raw: unknown) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [q, setQ] = useState("");
  const [verdict, setVerdict] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ verdict, q, limit: "50" });
      const data = await apiFetch<HistoryResponse>(
        `/api/history?${params.toString()}`
      );
      setItems(data.products || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [verdict, q]);

  useEffect(() => {
    const t = setTimeout(load, q ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  async function openDetail(id: number) {
    setDetailLoading(true);
    setDetail(null);
    try {
      const data = await apiFetch<ProductDetail>(`/api/history/${id}`);
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load product");
    } finally {
      setDetailLoading(false);
    }
  }

  const columns: Column<HistoryItem>[] = [
    {
      key: "title",
      header: "Product",
      render: (r) => (
        <button
          onClick={() => openDetail(r.id)}
          className="text-left text-accent-blue hover:underline line-clamp-2"
        >
          {r.title}
        </button>
      ),
      sortValue: (r) => r.title,
    },
    {
      key: "price",
      header: "Price",
      align: "right",
      render: (r) => formatGBP(r.price),
      sortValue: (r) => r.price ?? -1,
    },
    {
      key: "profit",
      header: "Profit",
      align: "right",
      render: (r) =>
        r.profit != null ? (
          <span className={r.profit > 0 ? "text-accent-green" : "text-accent-red"}>
            {formatGBP(r.profit)}
          </span>
        ) : (
          <span className="text-text-dim">—</span>
        ),
      sortValue: (r) => r.profit ?? -1,
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (r) => (
        <Badge tone={(r.verdict || "pending").toLowerCase()}>
          {(r.verdict || "pending").toUpperCase()}
        </Badge>
      ),
      sortValue: (r) => r.verdict || "",
    },
    {
      key: "date",
      header: "Date",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {formatDate(r.created_at)}
        </span>
      ),
      sortValue: (r) => r.created_at,
    },
    {
      key: "open",
      header: "",
      align: "right",
      render: (r) => (
        <Button
          variant="ghost"
          className="!px-2 !py-1 text-xs"
          onClick={() => openDetail(r.id)}
        >
          Open
        </Button>
      ),
    },
  ];

  // Build a Scorecard-compatible payload from ProductDetail
  function detailAsScorecard(d: ProductDetail) {
    const ebay: ScrapedProduct = {
      source: "eBay UK",
      title: d.product.title,
      price: d.product.price,
      url: d.product.ebay_url,
      image_url: d.product.image_url,
      condition: d.product.condition,
      seller: d.product.seller,
    };
    const suppliers: ScrapedProduct[] = (d.suppliers || []).map((s) => ({
      source: s.supplier_name,
      title: s.supplier_title || s.supplier_name,
      price: s.supplier_price || 0,
      url: s.supplier_url || "",
      delivery_days_min: s.delivery_days_min,
      delivery_days_max: s.delivery_days_max,
    }));
    const filters = parseFilters(d.verdict?.filter_results);
    return {
      ebayProduct: ebay,
      demand: d.demand,
      suppliers,
      llmAnalysis: d.analysis
        ? {
            brand_verdict: d.analysis.brand_verdict,
            brand_reasoning: d.analysis.brand_reasoning,
            demand_assessment: d.analysis.demand_assessment,
            demand_reasoning: d.analysis.demand_reasoning,
            supplier_type_reasoning: d.analysis.supplier_match_notes,
            raw_response: d.analysis.llm_raw_response,
          }
        : null,
      verdict: d.verdict
        ? {
            verdict: d.verdict.verdict || "pending",
            profit: d.verdict.profit_amount ?? 0,
            margin: d.verdict.profit_margin ?? 0,
            filters,
          }
        : null,
      scorecard: d.verdict?.scorecard || "",
    };
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">History</h1>
        <p className="text-sm text-text-secondary mt-1">
          Past analyses — open one to view its full scorecard
        </p>
      </div>

      <Card>
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by product title…"
            />
          </div>
          <select
            value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            className="bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            <option value="All">All verdicts</option>
            <option value="pass">PASS</option>
            <option value="fail">FAIL</option>
            <option value="pending">PENDING</option>
          </select>
        </div>
      </Card>

      {detailLoading && (
        <Card>
          <Spinner label="Loading product detail…" />
          <div className="mt-4 space-y-2" aria-hidden>
            <div className="skeleton h-40 rounded-xl" />
            <div className="skeleton h-24 rounded-xl" />
          </div>
        </Card>
      )}

      {detail && (
        <Card
          title="Product detail"
          action={
            <Button variant="ghost" onClick={() => setDetail(null)}>
              Close
            </Button>
          }
        >
          <Scorecard {...detailAsScorecard(detail)} />
        </Card>
      )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {loading ? (
        <Card>
          <Spinner label="Loading history…" />
          <div className="mt-4 space-y-2" aria-hidden>
            <div className="skeleton h-12 rounded-lg" />
            <div className="skeleton h-12 rounded-lg" />
            <div className="skeleton h-12 rounded-lg" />
          </div>
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={items}
          keyFn={(r) => r.id}
          emptyMessage={
            q || verdict !== "All"
              ? "No analyses match this filter."
              : "No analyses yet — run one from the Analyze page."
          }
        />
      )}
    </div>
  );
}
