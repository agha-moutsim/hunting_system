"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import FilterChecks from "@/components/FilterChecks";
import RangeControl from "@/components/ui/RangeControl";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import ProvenanceSelect from "@/components/ui/ProvenanceSelect";
import EbayStoresCard from "@/components/EbayStoresCard";
import { SoldPriceDistribution } from "@/components/charts";
import { ApiError, apiFetch, apiPost, downloadFile } from "@/lib/api";
import { infoTitle } from "@/lib/provenance";
import { headerStamps } from "@/lib/fieldProvenance";
import {
  DeepSearchJobResult,
  JobStarted,
  isTerminalJobStatus,
  jobFailureMessage,
  nextPollDelay,
} from "@/lib/deepSearchJob";
import {
  DeepSearchResult,
  FiltersResponse,
  PriceRange,
  ProvenanceInfo,
} from "@/lib/types";
import { formatGBP, formatPercent } from "@/lib/format";

export default function DeepSearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"fast" | "full">("fast");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DeepSearchResult | null>(null);
  const [activeRange, setActiveRange] = useState<PriceRange | null>(null);

  // C13 - every header number gets its stamp before it is rendered, so a
  // value can never reach this screen bare (see lib/fieldProvenance).
  const stamps = headerStamps(result?.provenance?.fields);

  useEffect(() => {
    apiFetch<FiltersResponse>("/api/filters")
      .then((d) => setActiveRange(d.range))
      .catch(() => setActiveRange(null));
  }, []);

  async function run(e?: FormEvent) {
    e?.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      if (mode === "full") {
        // B1 — the request hands back a job id in milliseconds. The run,
        // and the LLM verdict at the end of it, happens in the background:
        // a full run costs 282s on this machine, which is why it used to
        // time out on every attempt.
        const started = await apiPost<JobStarted>("/api/deep-search", {
          query: query.trim(),
        });
        await pollJob(started.job_id);
      } else {
        const data = await apiPost<DeepSearchResult>("/api/deep-search/fast", {
          query: query.trim(),
        });
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deep search failed");
    } finally {
      setLoading(false);
    }
  }

  async function pollJob(jobId: string): Promise<void> {
    let attempts = 0;
    for (;;) {
      const delay = nextPollDelay(attempts);
      if (delay === null) {
        setError(
          "The background job has not reported back — the backend may have restarted. Retry."
        );
        return;
      }
      await new Promise((r) => setTimeout(r, delay));

      let body: DeepSearchJobResult;
      try {
        body = await apiFetch<DeepSearchJobResult>(
          `/api/deep-search/jobs/${jobId}`
        );
      } catch (err) {
        setError(
          err instanceof ApiError && err.status === 404
            ? "That search is no longer available — the backend restarted. Run it again."
            : err instanceof Error
              ? err.message
              : "Lost contact with the search job."
        );
        return;
      }

      // Render what has arrived already: verified eBay and supplier data
      // shows up stage by stage instead of waiting on the model.
      setResult(body);
      const failure = jobFailureMessage(body);
      if (failure) setError(failure);

      if (isTerminalJobStatus(body.job_status)) return;
      attempts += 1;
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
        <Badge tone="info">
          Active range{" "}
          {activeRange ? `£${activeRange.min}–£${activeRange.max}` : "…"}
        </Badge>
      </div>
      <p className="text-sm text-text-secondary">
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
                className="bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:border-accent-blue"
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

      <RangeControl onApplied={(r) => setActiveRange(r)} />

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
          <ProvenanceSelect />
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <Badge tone={v}>{v}</Badge>
                  <span className="text-xs text-text-dim">
                    Competition: {result.competition_level || "—"} · Profit
                    potential: {result.profit_potential || "—"}
                  </span>
                </div>
                <h2 className="text-lg font-bold text-text-primary">
                  {result.product_name}
                </h2>
                <p className="text-sm text-text-secondary mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{result.product_category}</span>
                  <span className="inline-flex items-center gap-1">
                    {result.ebay_items_sold_month}
                    <ProvenanceBadge
                      provenance={stamps.ebay_items_sold_month.provenance}
                      label={stamps.ebay_items_sold_month.label}
                      title={infoTitle(stamps.ebay_items_sold_month)}
                    />
                  </span>
                  <span className="inline-flex items-center gap-1">
                    Sold 30d: {result.ebay_total_sold_30d ?? "-"}
                    <ProvenanceBadge
                      provenance={stamps.ebay_total_sold_30d.provenance}
                      label={stamps.ebay_total_sold_30d.label}
                      title={infoTitle(stamps.ebay_total_sold_30d)}
                    />
                  </span>
                  <span className="inline-flex items-center gap-1">
                    Sold 7d: {result.ebay_total_sold_7d ?? "-"}
                    <ProvenanceBadge
                      provenance={stamps.ebay_total_sold_7d.provenance}
                      label={stamps.ebay_total_sold_7d.label}
                      title={infoTitle(stamps.ebay_total_sold_7d)}
                    />
                  </span>
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => exportResult("csv")}>
                  Export CSV
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => exportResult("json")}
                >
                  Export JSON
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
              {(
                [
                  {
                    label: "eBay avg",
                    prov: stamps.ebay_avg_price,
                    value: formatGBP(result.ebay_avg_price),
                  },
                  {
                    label: "Range",
                    prov: stamps.ebay_price_min,
                    value: `${formatGBP(result.ebay_price_min)} – ${formatGBP(result.ebay_price_max)}`,
                  },
                  {
                    label: "Best supplier",
                    prov: stamps.best_supplier_price,
                    value: formatGBP(result.best_supplier_price),
                  },
                  {
                    label: "Profit / Margin",
                    value: (
                      <span
                        className={
                          result.profit > 0
                            ? "text-accent-green"
                            : "text-accent-red"
                        }
                      >
                        {formatGBP(result.profit)} /{" "}
                        {formatPercent(result.margin)}
                      </span>
                    ),
                    prov: result.provenance?.profit_analysis,
                  },
                ] as {
                  label: string;
                  value: React.ReactNode;
                  prov?: ProvenanceInfo;
                }[]
              ).map((m) => (
                <div
                  key={m.label}
                  className="bg-bg-surface border border-border rounded-lg p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                    <div className="text-xs text-text-secondary">{m.label}</div>
                    {m.prov && (
                      <ProvenanceBadge
                        provenance={m.prov.provenance}
                        label={m.prov.label}
                        title={infoTitle(m.prov)}
                      />
                    )}
                  </div>
                  <div className="text-base font-bold text-text-primary">
                    {m.value}
                  </div>
                </div>
              ))}
            </div>

            {/* Goal 4 — the observations behind the "eBay avg" and "Range"
              tiles, plotted from the SAME list that produced them, so the
              shape of the market is shown rather than asserted by three
              numbers. Holds no per-sale prices and it says so instead of
              drawing a bar over a gap. */}
            <div className="mt-3 bg-bg-surface border border-border rounded-control p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-dim mb-2">
                Sold price distribution
              </div>
              <SoldPriceDistribution
                prices={result.sold_prices}
                average={result.ebay_avg_price}
                stamps={{
                  count: stamps.sold_prices,
                  avg: stamps.ebay_avg_price,
                  range: stamps.ebay_price_min,
                }}
              />
            </div>
          </Card>

          {/* Filters */}
          {result.filters_passed?.length > 0 && (
            <Card title="Filter Checks">
              <FilterChecks filters={result.filters_passed} />
            </Card>
          )}

          {/* Competitor stores (C11) — legacy top-seller rows as fallback */}
          {Array.isArray(result.ebay_stores) ? (
            <EbayStoresCard stores={result.ebay_stores} />
          ) : (
            result.ebay_top_sellers?.length > 0 && (
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
                      <span className="flex items-center gap-2 min-w-0">
                        <span className="text-text-primary truncate">
                          {s.name}
                        </span>
                        <ProvenanceBadge
                          provenance={s.provenance}
                          label={s.provenance_label}
                        />
                      </span>
                      <span className="text-text-secondary whitespace-nowrap">
                        {s.sold_count ?? "—"} observed listings ·{" "}
                        {formatGBP(s.avg_price)}
                      </span>
                    </a>
                  ))}
                </div>
              </Card>
            )
          )}

          {/* Suppliers */}
          <div>
            <h3 className="text-sm font-semibold text-text-primary mb-3 flex flex-wrap items-center gap-2">
              Suppliers ({result.suppliers?.length || 0})
              {result.provenance?.suppliers && (
                <ProvenanceBadge
                  provenance={result.provenance.suppliers.provenance}
                  label={result.provenance.suppliers.label}
                  title={infoTitle(result.provenance.suppliers)}
                />
              )}
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
                          <ProvenanceBadge
                            provenance={s.provenance}
                            label={s.provenance_label}
                            title={s.source_name}
                          />
                        </div>
                        <div className="text-sm text-text-primary truncate">
                          {s.product_title || s.full_name || "—"}
                        </div>
                        <div className="text-xs text-text-dim mt-1">
                          Delivery:{" "}
                          {s.delivery_days ?? (
                            <ProvenanceBadge
                              provenance="unverified"
                              title="Delivery not confirmed for this row"
                            />
                          )}{" "}
                          · Rating:{" "}
                          {s.seller_rating ?? (
                            <ProvenanceBadge
                              provenance="unverified"
                              title="Seller rating not confirmed for this row"
                            />
                          )}
                        </div>
                        {(s.source_name || s.match_basis) && (
                          <div className="text-xs text-text-dim mt-1">
                            {/* Not a link: this row is already an <a>, and
                                nested anchors break HTML parsing. */}
                            {s.source_name && (
                              <span title={s.source_url || undefined}>
                                Source: {s.source_name}
                              </span>
                            )}
                            {s.source_name && s.match_basis && " · "}
                            {s.match_basis && <>Match: {s.match_basis}</>}
                          </div>
                        )}
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
                  ⚠️ No supplier matches found for this query (may be
                  rate-limited).
                </div>
              </Card>
            )}
          </div>

          {/* Notes + sources */}
          {(result.notes || result.sources?.length) && (
            <Card title="Notes & Sources">
              {result.notes && (
                <p className="text-sm text-text-secondary mb-3">
                  {result.notes}
                </p>
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
