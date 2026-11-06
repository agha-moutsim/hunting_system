import type {
  DemandData,
  FilterCheck,
  LLMAnalysis,
  ProductDetail,
  ScrapedProduct,
  VerdictData,
} from "./types";

/**
 * The History detail payload, shaped for `Scorecard`.
 *
 * Extracted from the page so the translation is testable on its own. The rule
 * it exists to protect is C1: a figure the API served as null stays null all
 * the way into the component. A `?? 0` here would print a price nobody
 * measured, and the page is the only place that would have done it.
 */
export interface HistoryScorecardProps {
  ebayProduct: ScrapedProduct;
  demand: DemandData | null;
  suppliers: ScrapedProduct[];
  llmAnalysis: LLMAnalysis | null;
  verdict: VerdictData | null;
  scorecard: string;
  profitComputed?: boolean;
  /** A stored scorecard's own legacy placeholders, called out before it is read. */
  scorecardWarning?: string | null;
}

/**
 * C1 — a scorecard written before `profit_computed` existed may still say
 * "Profit: £0.00 | Margin: 0.0%" for a run that never had a supplier price.
 * Replaying it beside an honest "Not computed" tile would contradict itself,
 * so the stored text gets a warning instead of a silent contradiction.
 */
export function legacyPlaceholderWarning(
  scorecard: string,
  profitComputed?: boolean
): string | null {
  if (profitComputed !== false || !scorecard) return null;
  const claimsProfit = /profit:[^\n]*\b0\.00\b/i.test(scorecard);
  const claimsMargin = /margin:[^\n]*\b0\.0\s*%/i.test(scorecard);
  if (!claimsProfit && !claimsMargin) return null;
  return (
    "This scorecard was saved before profit flags existed. The £0.00 and " +
    "0.0% it shows are placeholders, not a measured result."
  );
}

export function parseFilters(raw: unknown): FilterCheck[] {
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

export function detailAsScorecard(d: ProductDetail): HistoryScorecardProps {
  const ebay: ScrapedProduct = {
    source: "eBay UK",
    title: d.product.title,
    price: d.product.price,
    url: d.product.ebay_url,
    image_url: d.product.image_url,
    condition: d.product.condition,
    seller: d.product.seller,
    outside_band: d.product.outside_band,
    provenance: d.product.provenance,
    provenance_label: d.product.provenance_label,
  };
  const suppliers: ScrapedProduct[] = (d.suppliers || []).map((s) => ({
    source: s.supplier_name,
    title: s.supplier_title || s.supplier_name,
    price: s.supplier_price || 0,
    url: s.supplier_url || "",
    delivery_days_min: s.delivery_days_min,
    delivery_days_max: s.delivery_days_max,
    // C13 — replayed rows carry the same markers as live ones. `null` and
    // absent both mean "the row never stated it", so they collapse to
    // undefined here: either way SupplierCard renders no badge rather than
    // a claim that the row was verified.
    provenance: s.provenance ?? undefined,
    provenance_label: s.provenance_label ?? undefined,
    verified: s.verified ?? undefined,
    fetch_method: s.fetch_method ?? undefined,
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
          // C1 — null means "never computed" (no supplier price), and the
          // scorecard says so rather than printing a £0.00 nobody measured.
          profit: d.verdict.profit_amount ?? null,
          margin: d.verdict.profit_margin ?? null,
          filters,
        }
      : null,
    scorecard: d.verdict?.scorecard || "",
    profitComputed: d.profit_computed,
    scorecardWarning: legacyPlaceholderWarning(
      d.verdict?.scorecard || "",
      d.profit_computed
    ),
  };
}
