"use client";

import {
  ScrapedProduct,
  DemandData,
  LLMAnalysis,
  ProvenanceBlock,
  ProvenanceInfo,
  VerdictData,
} from "@/lib/types";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import OutsideBandBadge from "@/components/ui/OutsideBandBadge";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import FilterChecks from "@/components/FilterChecks";
import { fieldProvenance, infoTitle } from "@/lib/provenance";
import { formatGBP, formatPercent } from "@/lib/format";
import SupplierCard from "@/components/SupplierCard";

function Metric({
  label,
  value,
  prov,
}: {
  label: string;
  value: React.ReactNode;
  prov?: ProvenanceInfo;
}) {
  return (
    <div className="bg-bg-surface border border-border rounded-control p-3">
      <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-text-dim">
          {label}
        </div>
        {prov && (
          <ProvenanceBadge
            provenance={prov.provenance}
            label={prov.label}
            title={infoTitle(prov)}
          />
        )}
      </div>
      <div className="text-lg font-bold text-white font-mono tabular-nums">
        {value}
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
      <span className="w-1.5 h-1.5 rounded-full bg-brand-lime shrink-0" />
      {children}
    </h3>
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
        <p className="text-xs text-text-dim mt-1 leading-relaxed">
          {reasoning}
        </p>
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
  provenance,
}: {
  ebayProduct: ScrapedProduct;
  demand?: DemandData | null;
  suppliers: ScrapedProduct[];
  llmAnalysis?: LLMAnalysis | null;
  verdict?: VerdictData | null;
  scorecard?: string;
  provenance?: ProvenanceBlock;
}) {
  const v = (verdict?.verdict || "pending").toLowerCase();
  const priceRange =
    demand &&
    demand.lowest_sold_price != null &&
    demand.highest_sold_price != null
      ? `${formatGBP(demand.lowest_sold_price)} – ${formatGBP(demand.highest_sold_price)}`
      : "⚠️ Unverified";

  // Section-level stamp: the provenance block wins, else the demand object's
  // own tier. Undefined = no badge at all (never a fabricated one).
  const demandProv: ProvenanceInfo | undefined =
    provenance?.demand ??
    (demand?.provenance
      ? { provenance: demand.provenance, label: demand.provenance_label }
      : undefined);
  const demandField = (name: string, ...aliases: string[]) =>
    fieldProvenance(provenance?.fields, name, ...aliases);

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-col sm:flex-row gap-5">
          {ebayProduct.image_url && (
            <img
              src={ebayProduct.image_url}
              alt=""
              className="w-full sm:w-40 h-40 object-contain bg-white rounded-control p-2"
            />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-3 mb-3">
              <h2 className="text-lg font-bold text-white leading-snug">
                {ebayProduct.title}
              </h2>
              <Badge tone={v}>{v.toUpperCase()}</Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
              <Metric
                label="Listed Price"
                value={
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    {formatGBP(ebayProduct.price)}
                    {ebayProduct.outside_band && <OutsideBandBadge />}
                  </span>
                }
              />
              <Metric label="Condition" value={ebayProduct.condition || "—"} />
              <Metric label="Seller" value={ebayProduct.seller || "—"} />
            </div>
            {ebayProduct.url && (
              <a
                href={ebayProduct.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-brand-lime font-medium hover:underline"
              >
                View on eBay →
              </a>
            )}
          </div>
        </div>
      </Card>

      {suppliers.length > 0 && (
        <div>
          <SectionTitle>Price Comparison</SectionTitle>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <Metric label="eBay Price" value={formatGBP(ebayProduct.price)} />
            {suppliers.slice(0, 5).map((s, i) => {
              const delta = ebayProduct.price - s.price;
              return (
                <div
                  key={i}
                  className="bg-bg-surface border border-border rounded-control p-3"
                >
                  <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-text-dim mb-1">
                    {s.source}
                  </div>
                  <div className="text-lg font-bold text-white font-mono tabular-nums">
                    {formatGBP(s.price)}
                  </div>
                  <div
                    className={`text-xs mt-1 font-medium font-mono tabular-nums ${
                      delta > 0 ? "text-brand-lime" : "text-accent-red"
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

      {suppliers.length > 0 && (
        <div>
          <SectionTitle>Supplier Matches ({suppliers.length})</SectionTitle>
          <div className="space-y-3">
            {suppliers.map((s, i) => (
              <SupplierCard
                key={i}
                supplier={s}
                ebayPrice={ebayProduct.price}
              />
            ))}
          </div>
        </div>
      )}

      <div>
        <SectionTitle>
          Demand Metrics
          {demandProv && (
            <ProvenanceBadge
              provenance={demandProv.provenance}
              label={demandProv.label}
              title={infoTitle(demandProv)}
            />
          )}
        </SectionTitle>
        {demand && demand.sold_count_30d != null ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Metric
              label="Sold (30d)"
              value={demand.sold_count_30d ?? 0}
              prov={demandField("sold_count_30d")}
            />
            <Metric
              label="Sold (7d)"
              prov={demandField("sold_count_7d")}
              value={
                demand.sold_count_7d ?? (
                  <span className="text-accent-amber">⚠️ Unverified</span>
                )
              }
            />
            <Metric
              label="Avg Sold Price"
              prov={demandField("avg_sold_price")}
              value={
                demand.avg_sold_price != null
                  ? formatGBP(demand.avg_sold_price)
                  : "⚠️ Unverified"
              }
            />
            <Metric
              label="Price Range"
              prov={demandField("price_range", "lowest_sold_price")}
              value={priceRange}
            />
          </div>
        ) : (
          <div className="bg-bg-surface border border-border rounded-control p-4 text-sm text-text-secondary">
            ⚠️ No demand data available — marked Unverified
          </div>
        )}
      </div>

      {llmAnalysis && (
        <div>
          <SectionTitle>AI Analysis</SectionTitle>
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
              <summary className="text-xs text-text-dim cursor-pointer hover:text-white">
                Raw LLM response
              </summary>
              <pre className="mt-2 text-[11px] font-mono bg-bg-primary border border-border rounded-control p-3 overflow-x-auto text-text-secondary">
                {llmAnalysis.raw_response}
              </pre>
            </details>
          )}
        </div>
      )}

      {verdict && (
        <div>
          <SectionTitle>Verdict</SectionTitle>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <Metric
              label="Profit"
              prov={provenance?.profit_analysis}
              value={
                <span
                  className={
                    (verdict.profit ?? 0) > 0
                      ? "text-brand-lime"
                      : "text-accent-red"
                  }
                >
                  {formatGBP(verdict.profit)}
                </span>
              }
            />
            <Metric
              label="Margin"
              prov={provenance?.profit_analysis}
              value={formatPercent(verdict.margin)}
            />
            <Metric
              label="Verdict"
              value={<Badge tone={v}>{v.toUpperCase()}</Badge>}
            />
          </div>
          <div className="space-y-2">
            <FilterChecks filters={verdict.filters || []} />
          </div>
        </div>
      )}

      {scorecard && (
        <details>
          <summary className="text-sm text-text-secondary cursor-pointer hover:text-white mb-2">
            Full Scorecard
          </summary>
          <pre className="text-xs font-mono bg-bg-primary border border-border rounded-control p-4 overflow-x-auto text-text-secondary leading-relaxed mt-2">
            {scorecard}
          </pre>
        </details>
      )}
    </div>
  );
}
