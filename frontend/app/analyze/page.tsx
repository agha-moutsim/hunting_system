"use client";

import { useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Spinner from "@/components/Spinner";
import Scorecard from "@/components/Scorecard";
import { apiPost } from "@/lib/api";
import { AnalyzeResponse } from "@/lib/types";

export default function AnalyzePage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);

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
        <h1 className="text-xl font-bold text-text-primary">Analyze</h1>
        <p className="text-sm text-text-secondary mt-1">
          Full sourcing analysis: eBay → demand → 7 suppliers → AI → scorecard
        </p>
      </div>

      <Card className="bg-gradient-to-br from-bg-secondary to-bg-primary">
        <form onSubmit={onSubmit} className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Paste an eBay UK URL or type a search query (e.g. wireless earbuds)"
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
          Takes ~3 minutes (7 scrapers + LLM). Results are saved to History.
        </p>
      </Card>

      {loading && (
        <Card>
          <div className="flex flex-col items-center gap-4 py-6">
            <Spinner size="lg" label="Running analysis — this takes about 3 minutes…" />
            <div className="w-full max-w-md space-y-2" aria-hidden>
              <div className="skeleton h-20 rounded-xl" />
              <div className="skeleton h-10 rounded-lg" />
              <div className="skeleton h-10 rounded-lg" />
              <div className="skeleton h-10 rounded-lg" />
            </div>
            <p className="text-xs text-text-dim text-center">
              Scraping eBay, demand data, 7 suppliers, then LLM verdict.
            </p>
          </div>
        </Card>
      )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {result?.ebay_product && (
        <Scorecard
          ebayProduct={result.ebay_product}
          demand={result.demand}
          suppliers={result.supplier_matches || []}
          llmAnalysis={result.llm_analysis}
          verdict={result.verdict}
          scorecard={result.scorecard}
        />
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
