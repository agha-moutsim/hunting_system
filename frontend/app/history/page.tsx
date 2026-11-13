"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Card from "@/components/ui/Card";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Spinner from "@/components/Spinner";
import DataTable, { Column } from "@/components/DataTable";
import Scorecard from "@/components/Scorecard";
import EmptyState from "@/components/EmptyState";
import RangeFilterBar from "@/components/ui/RangeFilterBar";
import OutsideBandBadge from "@/components/ui/OutsideBandBadge";
import { apiFetch } from "@/lib/api";
import { useMarketplace } from "@/lib/marketplace";
import {
  HistoryItem,
  HistoryListResponse,
  PriceRange,
  ProductDetail,
} from "@/lib/types";
import {
  formatMoney,
  formatPrice,
  formatDate,
  priceSortKey,
  profitSortKey,
  truncate,
  verdictSortKey,
} from "@/lib/format";
import { detailAsScorecard } from "@/lib/historyDetail";

export default function HistoryPage() {
  const { marketplace } = useMarketplace();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [q, setQ] = useState("");
  const [verdict, setVerdict] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [viewMin, setViewMin] = useState("");
  const [viewMax, setViewMax] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [rangeFilter, setRangeFilter] = useState<PriceRange | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ verdict, q, limit: "50" });
      if (viewMin && viewMax) {
        params.set("price_min", viewMin);
        params.set("price_max", viewMax);
      }
      const data = await apiFetch<HistoryListResponse>(
        `/api/history?${params.toString()}`
      );
      setItems(data.products || []);
      setRangeFilter(data.range_filter || null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [verdict, q, viewMin, viewMax, reloadKey, marketplace.id]);

  useEffect(() => {
    // The list is scoped to the selected market, and a view range typed for
    // one market's prices is not a range in another. Clearing it reloads the
    // list under the new market's own band.
    setViewMin("");
    setViewMax("");
  }, [marketplace.id]);

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
      render: (r) => (
        <span className="inline-flex items-center justify-end gap-1.5">
          {formatPrice(r.price, r.currency || "GBP")}
          {r.outside_band && <OutsideBandBadge />}
        </span>
      ),
      sortValue: (r) => priceSortKey(r.price),
    },
    {
      key: "profit",
      header: "Profit",
      align: "right",
      render: (r) =>
        r.profit != null ? (
          <span
            className={r.profit > 0 ? "text-accent-green" : "text-accent-red"}
          >
            {formatMoney(r.profit, r.currency || "GBP")}
          </span>
        ) : (
          <span className="text-text-dim">—</span>
        ),
      sortValue: (r) => profitSortKey(r.profit),
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
          // C1 — the History query is an outer join, so a row can carry no
          // verdict at all. "PENDING" claims the engine is still working on
          // it; nothing is.
          <Badge tone="neutral" title="This run stored no verdict">
            NOT RECORDED
          </Badge>
        ),
      sortValue: (r) => verdictSortKey(r.verdict),
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
          className="px-2! py-1! text-xs"
          onClick={() => openDetail(r.id)}
        >
          Open
        </Button>
      ),
    },
  ];

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
              id="history-query"
              name="q"
              aria-label="Search by product title"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by product title…"
            />
          </div>
          <select
            id="history-verdict"
            name="verdict"
            aria-label="Verdict filter"
            value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            className="bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:border-accent-blue"
          >
            <option value="All">All verdicts</option>
            <option value="pass">PASS</option>
            <option value="fail">FAIL</option>
            <option value="pending">PENDING</option>
          </select>
        </div>
        <div className="mt-3 pt-3 border-t border-border">
          <RangeFilterBar
            initial={rangeFilter}
            symbol={marketplace.currency_symbol}
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
            <div className="flex items-center gap-2">
              {/* PHASE C — the route to what this card cannot show: which of the
                  figures below were measured, by what, when, and which were
                  never measured at all. */}
              <Link
                href={`/sources?product=${detail.product.id}`}
                className="rounded-control px-3 py-1.5 text-sm font-semibold text-text-secondary transition-colors duration-200 hover:bg-bg-surface hover:text-white"
              >
                Sources
              </Link>
              <Button variant="ghost" onClick={() => setDetail(null)}>
                Close
              </Button>
            </div>
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
            q || verdict !== "All" || viewMin || viewMax
              ? "No analyses match this filter."
              : "No analyses yet — run one from the Analyze page."
          }
        />
      )}
    </div>
  );
}
