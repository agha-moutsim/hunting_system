"use client";

import { useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import { apiPost, downloadFile } from "@/lib/api";
import { DeepSearchResult } from "@/lib/types";
import { formatGBP, formatPercent } from "@/lib/format";

export default function DeepSearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"fast" | "full">("fast");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DeepSearchResult | null>(null);

  async function run(e?: FormEvent) {
    e?.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const path = mode === "full" ? "/api/deep-search" : "/api/deep-search/fast";
      const data = await apiPost<DeepSearchResult>(path, { query: query.trim() });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deep search failed");
    } finally {
      setLoading(false);
    }
  }

  async function exportResult(fmt: "csv" | "json") {
    if (!result) return;
    try {
      await downloadFile(`/api/export/${fmt}`, `deep_search.${fmt}`, "POST", {
        result,
      });
    } catch {
      setError("Export failed");
    }
  }

  const v = (result?.verdict || "").toUpperCase() || "PENDING";

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-text-primary">Deep Search</h1>
        <Badge tone="pass">Price band £5–£35</Badge>
      </div>
      <p className="text-sm text-text-secondary -mt-3">
        Deep research: eBay sold history + supplier prices + verdict
      </p>

      <Card>
        <form onSubmit={run} className="space-y-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="flex-1">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Product name or eBay URL…"
                disabled={loading}
              />
            </div>
            <div className="flex gap-2">
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as "fast" | "full")}
                disabled={loading}
                className="bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
              >
                <option value="fast">Fast (~15s, no LLM)</option>
                <option value="full">Full (LLM, minutes)</option>
              </select>
              <Button type="submit" disabled={loading || !query.trim()}>
                {loading ? "Searching…" : "Search"}
              </Button>
            </div>
          </div>
        </form>
      </Card>

      {loading && (
        <Card>
          <div className="py-6">
            <Spinner
              label={
                mode === "full"
                  ? "Full deep research with LLM — minutes…"
                  : "Fast deep search — about 15 seconds…"
              }
            />
            <div className="mt-4 space-y-2" aria-hidden>
              <div className="skeleton h-12 rounded-lg" />
              <div className="skeleton h-24 rounded-xl" />
              <div className="skeleton h-24 rounded-xl" />
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
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <Badge tone={v}>{v}</Badge>
                  <span className="text-xs text-text-dim">
                    Competition: {result.competition_level || "—"} · Profit potential:{" "}
                    {result.profit_potential || "—"}
                  </span>
                </div>
                <h2 className="text-lg font-bold text-text-primary">
                  {result.product_name}
                </h2>
                <p className="text-sm text-text-secondary mt-1">
                  {result.product_category} · {result.ebay_items_sold_month} · Sold 30d:{" "}
                  {result.ebay_total_sold_30d ?? "⚠️ Unverified"} · Sold 7d:{" "}
                  {result.ebay_total_sold_7d ?? "⚠️ Unverified"}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => exportResult("csv")}>
                  Export CSV
                </Button>
                <Button variant="secondary" onClick={() => exportResult("json")}>
                  Export JSON
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
              {[
                { label: "eBay avg", value: formatGBP(result.ebay_avg_price) },
                {
                  label: "Range",
                  value: `${formatGBP(result.ebay_price_min)} – ${formatGBP(result.ebay_price_max)}`,
                },
                {
                  label: "Best supplier",
                  value: formatGBP(result.best_supplier_price),
                },
                {
                  label: "Profit / Margin",
                  value: (
                    <span
                      className={
                        result.profit > 0 ? "text-accent-green" : "text-accent-red"
                      }
                    >
                      {formatGBP(result.profit)} / {formatPercent(result.margin)}
                    </span>
                  ),
                },
              ].map((m) => (
                <div
                  key={m.label}
                  className="bg-bg-surface border border-border rounded-lg p-3"
                >
                  <div className="text-xs text-text-secondary mb-1">{m.label}</div>
                  <div className="text-base font-bold text-text-primary">{m.value}</div>
                </div>
              ))}
            </div>
          </Card>

          {/* Filters */}
          {result.filters_passed?.length > 0 && (
            <Card title="Filter Checks">
              <div className="space-y-2">
                {result.filters_passed.map((f, i) => (
                  <div
                    key={i}
                    className="flex flex-wrap items-center gap-2 text-sm bg-bg-surface border border-border rounded-lg px-3 py-2"
                  >
                    <Badge tone={f.passed ? "pass" : "fail"}>
                      {f.passed ? "PASS" : "FAIL"}
                    </Badge>
                    <span className="text-text-primary font-medium">{f.name}</span>
                    <span className="text-text-secondary">
                      {f.actual}{" "}
                      <span className="text-text-dim">(expected {f.expected})</span>
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Top sellers */}
          {result.ebay_top_sellers?.length > 0 && (
            <Card title="eBay Top Sellers">
              <div className="space-y-2">
                {result.ebay_top_sellers.map((s, i) => (
                  <a
                    key={i}
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-between gap-3 bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm hover:border-accent-blue/50"
                  >
                    <span className="text-text-primary truncate">{s.name}</span>
                    <span className="text-text-secondary whitespace-nowrap">
                      {s.sold_count ?? "—"} sold · {formatGBP(s.avg_price)}
                    </span>
                  </a>
                ))}
              </div>
            </Card>
          )}

          {/* Suppliers */}
          <div>
            <h3 className="text-sm font-semibold text-text-primary mb-3">
              Suppliers ({result.suppliers?.length || 0})
            </h3>
            {result.suppliers?.length ? (
              <div className="space-y-3">
                {result.suppliers.map((s, i) => (
                  <a
                    key={i}
                    href={s.url || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block bg-bg-secondary border border-border rounded-xl p-4 hover:border-accent-blue/50"
                  >
                    <div className="flex flex-wrap justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge tone="info">{s.name}</Badge>
                          {s.supplier_type && (
                            <span className="text-xs text-text-dim">
                              {s.supplier_type}
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-text-primary truncate">
                          {s.product_title || s.full_name || "—"}
                        </div>
                        <div className="text-xs text-text-dim mt-1">
                          Delivery: {s.delivery_days ?? "⚠️ Unverified"} · Rating:{" "}
                          {s.seller_rating ?? "⚠️ Unverified"}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-bold text-text-primary">
                          {formatGBP(s.price)}
                        </div>
                      </div>
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <Card>
                <div className="text-sm text-text-dim">
                  ⚠️ No supplier matches found for this query (may be rate-limited).
                </div>
              </Card>
            )}
          </div>

          {/* Notes + sources */}
          {(result.notes || result.sources?.length) && (
            <Card title="Notes & Sources">
              {result.notes && (
                <p className="text-sm text-text-secondary mb-3">{result.notes}</p>
              )}
              {result.sources?.length > 0 && (
                <ul className="text-xs text-text-dim space-y-1">
                  {result.sources.map((src, i) => (
                    <li key={i}>• {src}</li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}

      {!loading && !result && !error && (
        <Card>
          <div className="text-center py-8 text-sm text-text-dim">
            Enter a product name to run a deep search.
          </div>
        </Card>
      )}
    </div>
  );
}
