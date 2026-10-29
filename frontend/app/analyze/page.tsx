"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Spinner from "@/components/Spinner";
import Scorecard from "@/components/Scorecard";
import Badge from "@/components/ui/Badge";
import RangeControl from "@/components/ui/RangeControl";
import ProvenanceSelect from "@/components/ui/ProvenanceSelect";
import EbayStoresCard from "@/components/EbayStoresCard";
import { apiFetch, apiPost } from "@/lib/api";
import { useMarketplace } from "@/lib/marketplace";
import { AnalyzeResponse, FiltersResponse, PriceRange } from "@/lib/types";

export default function AnalyzePage() {
  const { marketplace } = useMarketplace();
  const marketIsUk = marketplace.id === "EBAY_GB";
  // Analyze and the standalone fee calculator are separate switches: AU runs
  // a full AUD analysis while its calculator stays locked until Phase E5.
  const fullAnalysis = marketplace.analyze_ready ?? marketIsUk;
  const supplierCount = marketplace.supplier_bench?.length ?? 0;
  const marketBand = marketplace.price_band;
  const historySaved = marketIsUk;
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  const [activeRange, setActiveRange] = useState<PriceRange | null>(null);

  useEffect(() => {
    apiFetch<FiltersResponse>("/api/filters")
      .then((d) => setActiveRange(d.range))
      .catch(() => setActiveRange(null));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const is_url =
        query.toLowerCase().includes("ebay") &&
        (query.includes("/itm/") || query.includes("/sch/"));
      setSubmittedQuery(is_url ? null : query.trim());
      const data = await apiPost<AnalyzeResponse>("/api/analyze", {
        query: query.trim(),
        is_url,
      });
      if (data.errors?.length && !data.ebay_product) {
        setError(data.errors.join(" · "));
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-text-primary">Analyze</h1>
          <Badge tone="info">
            {marketplace.label} · {marketplace.currency}
          </Badge>
          {marketIsUk && (
            <Badge tone="info">
              Active range{" "}
              {activeRange ? `£${activeRange.min}–£${activeRange.max}` : "…"}
            </Badge>
          )}
          {!marketIsUk && fullAnalysis && marketBand && (
            <Badge tone="info">
              {marketplace.currency_symbol}
              {marketBand.min.toFixed(2)}–{marketplace.currency_symbol}
              {marketBand.max.toFixed(2)} band
            </Badge>
          )}
        </div>
        <p className="text-sm text-text-secondary mt-1">
          {fullAnalysis
            ? `Full ${marketplace.currency} sourcing analysis: eBay → demand → ${supplierCount} suppliers → AI → scorecard`
            : `Search-only ${marketplace.label} analysis: real eBay listing and demand prices. Supplier costs and profit stay UK-only.`}
        </p>
      </div>

      <Card className="bg-linear-to-br from-bg-secondary to-bg-primary">
        <form onSubmit={onSubmit} className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Paste an eBay listing URL or type a search query (e.g. wireless earbuds)"
              disabled={loading}
            />
          </div>
          <Button
            type="submit"
            disabled={loading || !query.trim()}
            className="sm:w-32 justify-center"
          >
            {loading ? "Running…" : "Analyze"}
          </Button>
        </form>
        <p className="text-xs text-text-dim mt-2">
          Usually 30–90s (capped at 3 min).{" "}
          {historySaved
            ? "Results are saved to History."
            : "Results are not written to History yet: stored analyses carry no currency."}{" "}
          If it times out, retry or use Deep Search → Fast.
        </p>
      </Card>

      {marketIsUk && <RangeControl onApplied={(r) => setActiveRange(r)} />}

      {loading && (
        <Card>
          <div className="flex flex-col items-center gap-4 py-6">
            <Spinner
              size="lg"
              label="Running analysis — usually under 90 seconds…"
            />
            <div className="w-full max-w-md space-y-2" aria-hidden>
              <div className="skeleton h-20 rounded-xl" />
              <div className="skeleton h-10 rounded-lg" />
              <div className="skeleton h-10 rounded-lg" />
              <div className="skeleton h-10 rounded-lg" />
            </div>
            <p className="text-xs text-text-dim text-center">
              eBay → demand → {supplierCount} suppliers → verdict. Backend:{" "}
              <span className="font-mono">localhost:8000</span>
            </p>
          </div>
        </Card>
      )}

      {!fullAnalysis && (
        <Card className="border-accent-amber/40">
          <div className="text-sm text-accent-amber">
            {marketplace.fee_warning}
          </div>
          <p className="mt-1 text-xs text-text-secondary">
            Analyze can still read this market&apos;s eBay listing and demand
            prices. It returns no supplier matches, profit or verdict because
            those would mix {marketplace.currency} with GBP supplier costs.
          </p>
        </Card>
      )}

      {fullAnalysis &&
        !marketplace.fee_calculator_ready &&
        marketplace.fee_warning && (
          <Card className="border-accent-amber/40">
            <div className="text-sm text-accent-amber">
              {marketplace.fee_warning}
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              Analyze runs in {marketplace.currency} and prices with the
              registered card; the standalone fee calculator stays locked.
            </p>
          </Card>
        )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {/* PR-4: band/exclusion notes are shown even on a successful analysis */}
      {result?.ebay_product &&
        !!result.errors?.length &&
        result.errors.map((msg, i) => (
          <Card key={i} className="border-accent-amber/40">
            <div className="text-sm text-accent-amber">{msg}</div>
          </Card>
        ))}

      {result?.ebay_product && (
        <>
          <ProvenanceSelect />
          <Scorecard
            currency={result.currency || marketplace.currency}
            ebayProduct={result.ebay_product}
            demand={result.demand}
            suppliers={result.supplier_matches || []}
            llmAnalysis={result.llm_analysis}
            verdict={result.verdict}
            scorecard={result.scorecard}
            provenance={result.provenance}
            sellerQuery={submittedQuery}
          />
          {Array.isArray(result.ebay_stores) && (
            <EbayStoresCard stores={result.ebay_stores} />
          )}
        </>
      )}

      {!loading && !result && !error && (
        <Card>
          <div className="text-center py-8 text-sm text-text-dim">
            Enter a query above to run your first analysis.
          </div>
        </Card>
      )}
    </div>
  );
}
