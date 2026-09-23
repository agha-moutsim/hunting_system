"use client";

import { ScrapedProduct, DemandData, LLMAnalysis, VerdictData } from "@/lib/types";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import { formatGBP, formatPercent } from "@/lib/format";
import SupplierCard from "@/components/SupplierCard";

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-bg-surface border border-border rounded-lg p-3">
      <div className="text-xs text-text-secondary mb-1">{label}</div>
      <div className="text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

function LlmLine({
  label,
  value,
  reasoning,
  toneMap,
}: {
  label: string;
  value?: string | null;
  reasoning?: string | null;
  toneMap?: Record<string, string>;
}) {
  if (!value) return null;
  const key = value.toLowerCase();
  const tone =
    toneMap?.[key] ||
    (["generic", "strong", "source", "pass"].includes(key)
      ? "pass"
      : ["branded", "weak", "skip", "fail"].includes(key)
        ? "fail"
        : ["ambiguous", "moderate", "investigate", "pending"].includes(key)
          ? "pending"
          : "info");
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-text-secondary font-medium">{label}:</span>
        <Badge tone={tone}>{value}</Badge>
      </div>
      {reasoning && (
        <p className="text-xs text-text-dim mt-1 leading-relaxed">{reasoning}</p>
      )}
    </div>
  );
}

export default function Scorecard({
  ebayProduct,
  demand,
  suppliers,
  llmAnalysis,
  verdict,
  scorecard,
}: {
  ebayProduct: ScrapedProduct;
  demand?: DemandData | null;
  suppliers: ScrapedProduct[];
  llmAnalysis?: LLMAnalysis | null;
  verdict?: VerdictData | null;
  scorecard?: string;
}) {
  const v = (verdict?.verdict || "pending").toLowerCase();
  const priceRange =
    demand && demand.lowest_sold_price != null && demand.highest_sold_price != null
      ? `${formatGBP(demand.lowest_sold_price)} – ${formatGBP(demand.highest_sold_price)}`
      : "⚠️ Unverified";

  return (
    <div className="space-y-6">
      {/* Product Hero */}
      <Card>
        <div className="flex flex-col sm:flex-row gap-5">
          {ebayProduct.image_url && (
            <img
              src={ebayProduct.image_url}
              alt=""
              className="w-full sm:w-40 h-40 object-contain bg-white rounded-lg p-2"
            />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-3 mb-3">
              <h2 className="text-lg font-bold text-text-primary leading-snug">
                {ebayProduct.title}
              </h2>
              <Badge tone={v}>{v.toUpperCase()}</Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
              <Metric label="Listed Price" value={formatGBP(ebayProduct.price)} />
              <Metric label="Condition" value={ebayProduct.condition || "—"} />
              <Metric label="Seller" value={ebayProduct.seller || "—"} />
            </div>
            {ebayProduct.url && (
              <a
                href={ebayProduct.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-accent-blue hover:underline"
              >
                View on eBay →
              </a>
            )}
          </div>
        </div>
      </Card>

      {/* Price comparison */}
      {suppliers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            💰 Price Comparison
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <Metric label="eBay Price" value={formatGBP(ebayProduct.price)} />
            {suppliers.slice(0, 5).map((s, i) => {
              const delta = ebayProduct.price - s.price;
              return (
                <div
                  key={i}
                  className="bg-bg-surface border border-border rounded-lg p-3"
                >
                  <div className="text-xs text-text-secondary mb-1">{s.source}</div>
                  <div className="text-lg font-bold text-text-primary">
                    {formatGBP(s.price)}
                  </div>
                  <div
                    className={`text-xs mt-1 font-medium ${
                      delta > 0 ? "text-accent-green" : "text-accent-red"
                    }`}
                  >
                    {delta > 0 ? "+" : ""}
                    {formatGBP(delta)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Supplier cards */}
      {suppliers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            🏪 Supplier Matches ({suppliers.length})
          </h3>
          <div className="space-y-3">
            {suppliers.map((s, i) => (
              <SupplierCard key={i} supplier={s} ebayPrice={ebayProduct.price} />
            ))}
          </div>
        </div>
      )}

      {/* Demand */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">
          📊 Demand Metrics
        </h3>
        {demand && demand.sold_count_30d != null ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Metric label="Sold (30d)" value={demand.sold_count_30d ?? 0} />
            <Metric label="Sold (7d)" value={demand.sold_count_7d ?? 0} />
            <Metric
              label="Avg Sold Price"
              value={demand.avg_sold_price != null ? formatGBP(demand.avg_sold_price) : "⚠️ Unverified"}
            />
            <Metric label="Price Range" value={priceRange} />
          </div>
        ) : (
          <div className="bg-bg-surface border border-border rounded-lg p-4 text-sm text-text-secondary">
            ⚠️ No demand data available — marked Unverified
          </div>
        )}
      </div>

      {/* LLM */}
      {llmAnalysis && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            🤖 AI Analysis
          </h3>
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <LlmLine
                label="Brand"
                value={llmAnalysis.brand_verdict}
                reasoning={llmAnalysis.brand_reasoning}
              />
              <LlmLine
                label="Demand"
                value={llmAnalysis.demand_assessment}
                reasoning={llmAnalysis.demand_reasoning}
              />
            </div>
            <div>
              <LlmLine label="Action" value={llmAnalysis.recommended_action} />
              {llmAnalysis.supplier_type_reasoning && (
                <p className="text-xs text-text-dim leading-relaxed">
                  {llmAnalysis.supplier_type_reasoning}
                </p>
              )}
            </div>
          </div>
          {llmAnalysis.raw_response && (
            <details className="mt-3">
              <summary className="text-xs text-text-dim cursor-pointer hover:text-text-secondary">
                Raw LLM response
              </summary>
              <pre className="mt-2 text-[11px] bg-bg-primary border border-border rounded-lg p-3 overflow-x-auto text-text-secondary">
                {llmAnalysis.raw_response}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* Verdict + filters */}
      {verdict && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-3">✅ Verdict</h3>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <Metric
              label="Profit"
              value={
                <span
                  className={
                    (verdict.profit ?? 0) > 0 ? "text-accent-green" : "text-accent-red"
                  }
                >
                  {formatGBP(verdict.profit)}
                </span>
              }
            />
            <Metric label="Margin" value={formatPercent(verdict.margin)} />
            <Metric
              label="Verdict"
              value={
                <Badge tone={v}>{v.toUpperCase()}</Badge>
              }
            />
          </div>
          <div className="space-y-2">
            {(verdict.filters || []).map((f, i) => (
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
        </div>
      )}

      {/* Full scorecard */}
      {scorecard && (
        <details>
          <summary className="text-sm text-text-secondary cursor-pointer hover:text-text-primary mb-2">
            Full Scorecard
          </summary>
          <pre className="text-xs bg-bg-primary border border-border rounded-lg p-4 overflow-x-auto text-text-secondary leading-relaxed mt-2">
            {scorecard}
          </pre>
        </details>
      )}
    </div>
  );
}
