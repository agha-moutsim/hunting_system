"use client";

import { useState, useEffect, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import EbayStoresCard from "@/components/EbayStoresCard";
import { apiPost } from "@/lib/api";
import { BulkResponse, DeepSearchResult } from "@/lib/types";
import { formatMoney, formatPercent, truncate } from "@/lib/format";
import { useMarketplace } from "@/lib/marketplace";

export default function BulkPage() {
  const { marketplace } = useMarketplace();
  const marketIsUk = marketplace.id === "EBAY_GB";
  const analysisReady = marketplace.analyze_ready ?? marketIsUk;
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResponse | null>(null);

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [marketplace.id]);

  async function run(e: FormEvent) {
    e.preventDefault();
    const queries = text
      .split("\n")
      .map((q) => q.trim())
      .filter(Boolean);
    if (!queries.length || loading || !analysisReady) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await apiPost<BulkResponse>("/api/bulk", { queries });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk analysis failed");
    } finally {
      setLoading(false);
    }
  }

  function exportClient(fmt: "csv" | "json") {
    if (!result) return;
    const rows = result.results;
    if (fmt === "json") {
      const blob = new Blob([JSON.stringify(rows, null, 2)], {
        type: "application/json",
      });
      download(blob, "bulk_results.json");
    } else {
      const headers = [
        "Product",
        "Category",
        "Verdict",
        "eBay Avg",
        "Best Supplier",
        "Profit",
        "Margin %",
        "Sold 30d",
      ];
      const lines = [
        headers.join(","),
        ...rows.map((r) =>
          [
            csv(r.product_name),
            csv(r.product_category),
            r.verdict,
            r.ebay_avg_price,
            r.best_supplier_price,
            r.profit,
            r.margin,
            r.ebay_total_sold_30d,
          ].join(",")
        ),
      ];
      download(
        new Blob([lines.join("\n")], { type: "text/csv" }),
        "bulk_results.csv"
      );
    }
  }

  function download(blob: Blob, name: string) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }

  function csv(s: unknown) {
    const str = String(s ?? "");
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-text-primary">Bulk Analysis</h1>
        <Badge tone="info">
          {marketplace.currency} range{" "}
          {marketplace.price_band
            ? `${marketplace.currency_symbol}${marketplace.price_band.min}–${marketplace.currency_symbol}${marketplace.price_band.max}`
            : "…"}
        </Badge>
        <Badge tone="info">{marketplace.label}</Badge>
      </div>
      <p className="text-sm text-text-secondary mt-1">
        Fast-mode analysis for many queries at once (no LLM) in{" "}
        {marketplace.currency}
      </p>

      {!analysisReady && (
        <Card className="border-accent-amber/40">
          <div className="text-sm text-accent-amber">
            Bulk Analysis is not enabled for {marketplace.label}. A registered
            fee card and supplier bench are required before an{" "}
            {marketplace.currency} profit can be calculated. Switch to United
            Kingdom or use Deals and Titles to browse this market.
          </div>
        </Card>
      )}

      <Card>
        <form onSubmit={run} className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              "wireless earbuds\nphone case\nkitchen organizer\n…one query per line"
            }
            className="w-full bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-dim focus:outline-hidden focus:border-accent-blue min-h-[120px]"
            disabled={loading || !analysisReady}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              disabled={loading || !text.trim() || !analysisReady}
            >
              {loading ? "Running…" : "Run Bulk"}
            </Button>
            <span className="text-xs text-text-dim">
              {text.split("\n").filter((q) => q.trim()).length} query(ies)
            </span>
          </div>
        </form>
      </Card>

      {loading && (
        <Card>
          <div className="py-6">
            <Spinner label="Running fast deep search on each query…" />
            <div className="mt-4 space-y-2" aria-hidden>
              <div className="skeleton h-14 rounded-lg" />
              <div className="skeleton h-14 rounded-lg" />
              <div className="skeleton h-14 rounded-lg" />
            </div>
          </div>
        </Card>
      )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {result && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-text-secondary">
                {result.succeeded}/{result.total} succeeded
                {result.errors?.length > 0 &&
                  ` · ${result.errors.length} failed`}
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => exportClient("csv")}>
                  Export CSV
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => exportClient("json")}
                >
                  Export JSON
                </Button>
              </div>
            </div>
            {result.errors?.length > 0 && (
              <ul className="mt-3 text-xs text-accent-red space-y-1">
                {result.errors.map((e, i) => (
                  <li key={i}>
                    • {e.query}: {e.error}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="space-y-3">
            {result.results.map((r: DeepSearchResult, i) => (
              <Card key={i}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge tone={(r.verdict || "PENDING").toUpperCase()}>
                        {(r.verdict || "PENDING").toUpperCase()}
                      </Badge>
                      <span className="text-xs text-text-dim">
                        {r.product_category}
                      </span>
                    </div>
                    <div className="text-sm font-medium text-text-primary">
                      {truncate(r.product_name, 80)}
                    </div>
                    <div className="text-xs text-text-secondary mt-1">
                      eBay avg{" "}
                      {formatMoney(
                        r.ebay_avg_price,
                        r.currency || marketplace.currency
                      )}{" "}
                      · Best supplier{" "}
                      {formatMoney(
                        r.best_supplier_price,
                        r.currency || marketplace.currency
                      )}{" "}
                      · Sold 30d: {r.ebay_total_sold_30d ?? "⚠️ Unverified"}
                      {(() => {
                        const preferred =
                          r.suppliers?.filter((s) => s.sourcing_preferred)
                            .length ?? 0;
                        const bestTotal = (r.suppliers ?? []).reduce<
                          number | null
                        >(
                          (min, s) =>
                            s.total_landed_cost != null &&
                            (min == null || s.total_landed_cost < min)
                              ? s.total_landed_cost
                              : min,
                          null
                        );
                        if (!preferred && bestTotal == null) return null;
                        return (
                          <>
                            {preferred > 0 && ` · ${preferred} preferred`}
                            {bestTotal != null &&
                              ` · best total ${formatMoney(bestTotal, r.currency || marketplace.currency)}`}
                          </>
                        );
                      })()}
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={`text-lg font-bold ${
                        r.profit > 0 ? "text-accent-green" : "text-accent-red"
                      }`}
                    >
                      {formatMoney(
                        r.profit,
                        r.currency || marketplace.currency
                      )}
                    </div>
                    <div className="text-xs text-text-secondary">
                      {formatPercent(r.margin)}
                    </div>
                  </div>
                </div>
                {/* C11: competitor stores. These raws already carry them -
                    the block was simply never rendered, so the data reached
                    the browser and was discarded here. */}
                <div className="mt-3">
                  <EbayStoresCard
                    stores={r.ebay_stores}
                    provenance={r.ebay_stores_provenance}
                  />
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {!loading && !result && !error && (
        <Card>
          <div className="text-center py-8 text-sm text-text-dim">
            Paste one query per line to bulk-analyze.
          </div>
        </Card>
      )}
    </div>
  );
}
