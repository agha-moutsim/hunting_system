/** TypeScript mirrors of FastAPI Phase A responses. */

// ── Provenance (C13) ────────────────────────────────────────────

/** Four-tier provenance stamp on every factual value. */
export type Provenance = "verified" | "estimated" | "unverified" | "ai_insight";

/** Per-value / per-section provenance metadata. */
export interface ProvenanceInfo {
  provenance?: string;
  label?: string;
  source_url?: string;
  source_name?: string;
  method?: string;
  reason?: string;
  /**
   * REGRESSION-006: the C11 store block carries its own count so a partial
   * result can say so. A single store stamped "verified" is indistinguishable
   * from a full set, which is how a one-store result went unnoticed.
   */
  store_count?: number;
  max_stores?: number;
  /** True when the eBay query had to widen past the active buying band. */
  broadened?: boolean;
  query_used?: string;
  price_band_used?: [number, number] | null;
}

/** Top-level provenance block attached to analysis responses. */
export interface ProvenanceBlock {
  demand?: ProvenanceInfo;
  top_eBay_sellers?: ProvenanceInfo;
  suppliers?: ProvenanceInfo;
  profit_analysis?: ProvenanceInfo;
  fields?: Record<string, ProvenanceInfo>;
}

/**
 * Product-match tier (C14) — `""` / absent = never scored.
 * An unscored row must never render as a confident match (C13/C14).
 */
export type MatchTier = "verified" | "unverified" | "no_match" | "";

/** Stock state as the source stated it — `""` = unknown, never assumed. */
export type StockState = "in_stock" | "low_stock" | "out_of_stock" | "";

/**
 * Optional product-match + availability fields a supplier row may carry.
 * Every field is nullable: the backend may send rows without any of them
 * (older path, or the source never said). Missing renders as missing.
 */
export interface MatchAvailabilityFields {
  /** Computed 0.0–1.0 by the matcher — never a constant (C14). */
  match_score?: number | null;
  /** `""` / absent = never scored — must not read as a confident match. */
  match_tier?: MatchTier | null;
  /** Backend's own wording: "verified match" | "not confirmed" | "no confirmed match". */
  match_label?: string | null;
  /** Human-readable reason the score is what it is — tooltip only, never card body. */
  match_basis?: string | null;
  /** Names the scoring algorithm (audit trail). */
  match_method?: string | null;
  /** `""` = unknown — never assume in stock. */
  in_stock?: StockState | null;
  /** Exact source text, e.g. "Only 3 left" — shown verbatim when `in_stock` is `""`. */
  stock_raw?: string | null;
  availability_url?: string | null;
  /** 0.0 = UNKNOWN, not "free" — `shipping_raw` disambiguates. */
  shipping_cost?: number | null;
  /** 0 = unknown. */
  shipping_days?: number | null;
  /** Exact source text — authoritative when present. */
  shipping_raw?: string | null;
}

/** Competitor eBay store (C11 — up to 4, real seller usernames only). */
export interface EbayStore {
  name: string;
  url: string;
  /** true = the /str/ URL was derived from the username, not observed. */
  url_derived?: boolean;
  /** Listings observed in the search window (cap 50) — NOT eBay sold count. */
  sold_count: number;
  sold_count_label?: string;
  avg_price: number;
  provenance?: string;
  provenance_label?: string;
  source_name?: string;
}

// ── Filters / price range (GET-PUT /api/filters) ────────────────

export interface PriceRange {
  min: number;
  max: number;
}

export interface ActiveFilterSettings {
  price_min: number;
  price_max: number;
  demand_min_30d?: number;
  demand_min_7d?: number;
  delivery_min?: number;
  delivery_target_max?: number;
  margin_min?: number;
  brand_filter?: string;
  condition?: string;
  buy_it_now?: boolean;
  uk_only?: boolean;
}

export interface FiltersResponse {
  active: ActiveFilterSettings;
  range: PriceRange;
  defaults: { price_min: number; price_max: number };
}

export interface RangeUpdateBody {
  price_min: number;
  price_max: number;
}

export interface RangeUpdateResponse {
  range: PriceRange;
}

// ── Status ──────────────────────────────────────────────────────

export interface SystemStatus {
  db: boolean;
  ollama: boolean;
  ollama_model: string;
  ebay_api: boolean;
}

// ── Analyze ─────────────────────────────────────────────────────

export interface ScrapedProduct extends MatchAvailabilityFields {
  source: string;
  title: string;
  price: number;
  url: string;
  image_url?: string | null;
  delivery_days_min?: number | null;
  delivery_days_max?: number | null;
  seller?: string | null;
  seller_full_name?: string | null;
  seller_rating?: string | null;
  seller_orders?: string | null;
  store_name?: string | null;
  condition?: string;
  verified?: boolean;
  provenance?: string;
  provenance_label?: string;
  /** True when this price sits outside the active price range. */
  outside_band?: boolean;
}

export interface DemandData {
  sold_count_30d?: number | null;
  sold_count_7d?: number | null;
  last_sale_date?: string | null;
  avg_sold_price?: number | null;
  lowest_sold_price?: number | null;
  highest_sold_price?: number | null;
  verified?: boolean;
  provenance?: string;
  provenance_label?: string;
}

export interface LLMAnalysis {
  brand_verdict?: string;
  brand_reasoning?: string;
  demand_assessment?: string;
  demand_reasoning?: string;
  supplier_type_reasoning?: string;
  supplier_match_notes?: string;
  recommended_action?: string;
  raw_response?: string;
  llm_raw_response?: string;
}

export interface FilterCheck {
  name: string;
  passed: boolean;
  actual?: string;
  expected?: string;
  /** false = the API could not verify this row (renders as Unverified). */
  verified?: boolean;
  /** true = advisory row (e.g. "Delivery (advisory)") — never pass/fail. */
  advisory?: boolean;
  provenance?: string;
  provenance_label?: string;
}

export interface VerdictData {
  verdict: string; // pass | fail | pending
  profit?: number;
  margin?: number;
  filters?: FilterCheck[];
}

export interface AnalyzeResponse {
  ebay_product: ScrapedProduct | null;
  demand: DemandData | null;
  supplier_matches: ScrapedProduct[];
  llm_analysis: LLMAnalysis | null;
  verdict: VerdictData | null;
  scorecard: string;
  errors: string[];
  /** Top-level provenance block — NOT a per-row tier string. */
  provenance?: ProvenanceBlock;
  /** Competitor eBay stores (C11) — also returned by the URL-hunt path. */
  ebay_stores?: EbayStore[];
}

// ── Deep Search ─────────────────────────────────────────────────

export interface SupplierInfo extends Omit<
  MatchAvailabilityFields,
  "match_basis"
> {
  name: string;
  full_name?: string;
  price: number;
  url: string;
  supplier_type?: string;
  delivery_days?: string | number;
  seller_rating?: string | number;
  seller_orders?: string | number;
  product_title?: string;
  image_url?: string;
  notes?: string;
  provenance?: string;
  provenance_label?: string;
  source_url?: string;
  source_name?: string;
  match_basis?: string;
}

export interface TopSeller {
  name: string;
  url: string;
  sold_count?: number;
  avg_price?: number;
  provenance?: string;
  provenance_label?: string;
}

export interface DeepSearchResult {
  product_name: string;
  product_category: string;
  ebay_items_sold_month: string;
  ebay_top_sellers: TopSeller[];
  ebay_price_range: string;
  ebay_avg_price: number;
  ebay_price_min: number;
  ebay_price_max: number;
  ebay_price_median: number;
  ebay_total_sold_30d: number;
  ebay_total_sold_7d: number | null; // null = unknown (never estimated)
  suppliers: SupplierInfo[];
  best_supplier_price: number;
  profit: number;
  margin: number;
  verdict: string; // PASS | FAIL | PENDING
  filters_passed: FilterCheck[];
  competition_level: string;
  profit_potential: string;
  delivery_info: string;
  notes: string;
  sources: string[];
  raw_analysis: string;
  /** Top-level provenance block — NOT a per-row tier string. */
  provenance?: ProvenanceBlock;
  /** Competitor eBay stores (C11) — supersedes ebay_top_sellers. */
  ebay_stores?: EbayStore[];
  /**
   * C11/C13: the block stamp. REGRESSION-006 - a short list stamped
   * "verified" is indistinguishable from a full one, which is how a
   * single-store result went unnoticed.
   */
  ebay_stores_provenance?: ProvenanceInfo;
}

export interface BulkResponse {
  results: DeepSearchResult[];
  errors: { query: string; error: string }[];
  total: number;
  succeeded: number;
}

// ── Hunter ──────────────────────────────────────────────────────

/**
 * Why a row does or does not have a supplier price.
 * "" means it was never checked - which must not read like a check that
 * found nothing.
 */
export type SupplierStatus =
  "found" | "no_supplier" | "out_of_band" | "timeout" | "";

export interface CategoryProduct extends MatchAvailabilityFields {
  title: string;
  price: number;
  url: string;
  image_url?: string | null;
  seller?: string | null;
  condition?: string;
  category?: string;
  /** What was actually asked of eBay: "category" or "keyword". */
  search_mode?: string;
  /** The text really sent to eBay - not whatever the user retyped. */
  search_query?: string;
  sold_30d?: number;
  sold_7d?: number;
  supplier_price?: number;
  supplier_name?: string;
  supplier_url?: string;
  /** REGRESSION-004: the reason a supplier price is or is not there. */
  supplier_status?: SupplierStatus;
  supplier_status_reason?: string;
  /**
   * REGRESSION-005: `profit`/`margin` stay 0 when we have no data, so these
   * say whether the number is a calculation or the absence of one. A row
   * with `profit_provenance === "unverified"` must render as "no data",
   * never as GBP0.00.
   */
  profit_provenance?: "verified" | "estimated" | "unverified" | "ai_insight";
  profit_provenance_label?: string;
  profit_provenance_reason?: string;
  profit_provenance_method?: string;
  profit_status?: SupplierStatus;
  /** Supplier postage when the source stated it. 0.0 = unknown, not free. */
  shipping_cost?: number;
  shipping_raw?: string;
  /** Computed by hunter/demand_hotness.py from the two demand counts. */
  hot?: boolean;
  hot_basis?: string;
  hot_provenance?: "verified" | "unverified";
  hot_reason?: string;
  demand_pace_7d_per_week?: number | null;
  demand_pace_30d_per_week?: number | null;
  /** C11 competitor stores observed in this row's category scan. */
  ebay_stores?: EbayStore[];
  ebay_stores_provenance?: ProvenanceInfo;
  profit?: number;
  margin?: number;
  verdict?: string;
}

/** What a scan/browse actually resolved to, so the UI can state it. */
export interface HunterSearchInfo {
  text: string;
  mode: "category" | "keyword";
  label: string;
  reason: string;
}

export interface HunterCategory {
  label: string;
  category_id: string;
}

export interface HunterScanResponse {
  products: CategoryProduct[];
  total_scanned: number;
  total_with_demand: number;
  search?: HunterSearchInfo;
}

/**
 * Real counts behind the result, so "no products" is never ambiguous.
 * A run where every supplier lookup timed out must not look the same as a
 * category with nothing in it.
 */
export interface HunterLookupSummary {
  products_returned: number;
  with_supplier: number;
  no_supplier: number;
  timed_out: number;
  out_of_band: number;
  scanned: number;
  price_min: number;
  price_max: number;
  status_counts: Record<string, number>;
}

export interface HunterReport {
  category: string;
  price_min: number;
  price_max: number;
  total_scanned: number;
  total_with_demand: number;
  total_with_supplier: number;
  total_pass: number;
  hot_count?: number;
  products: CategoryProduct[];
  scanned_at: string;
  notes?: string; // PR-4 band-exclusion transparency line
  provenance?: {
    profit?: {
      provenance: string;
      label?: string;
      reason?: string;
      method?: string;
      rows_unverified: number;
      rows_total: number;
    };
    supplier_status_counts?: Record<string, number>;
  };
  summary?: HunterLookupSummary;
}

// ── Tracker ─────────────────────────────────────────────────────

export interface TrackedProduct {
  id: number;
  product_name: string;
  ebay_url: string;
  ebay_price: number;
  target_price: number;
  supplier_price: number;
  supplier_url: string;
  supplier_name: string;
  last_checked?: string | null;
  alert_enabled: boolean;
  created_at?: string | null;
  outside_band?: boolean;
}

export interface TrackerListResponse {
  products: TrackedProduct[];
  range_filter: PriceRange;
}

export interface PriceAlert {
  id: number;
  product_id: number;
  product_name: string;
  alert_type: string;
  message: string;
  old_price: number;
  new_price: number;
  is_read: boolean;
  created_at?: string | null;
}

export interface PriceHistoryPoint {
  ebay_price: number;
  supplier_price: number;
  checked_at?: string | null;
  outside_band?: boolean;
}

export interface TrackerHistoryResponse {
  history: PriceHistoryPoint[];
  trend: PriceTrend;
}

export interface PriceTrend {
  trend: "up" | "down" | "stable";
  change: number;
  change_percent: number;
}

// ── Watchlist ───────────────────────────────────────────────────

export interface WatchlistItem {
  id: number;
  product_name: string;
  ebay_url: string;
  ebay_price: number;
  target_price: number;
  supplier_price: number;
  supplier_url: string;
  supplier_name: string;
  notes: string;
  added_at?: string | null;
  outside_band?: boolean;
}

export interface WatchlistListResponse {
  items: WatchlistItem[];
  range_filter: PriceRange;
}

export interface SavedSearch {
  id: number;
  search_name: string;
  query: string;
  category: string;
  price_min: number;
  price_max: number;
  min_margin: number;
  auto_run: boolean;
  last_run?: string | null;
  created_at?: string | null;
  result_count: number;
  unread_count: number;
}

export interface SearchResult {
  id: number;
  search_id: number;
  search_name: string;
  product_name: string;
  ebay_url: string;
  ebay_price: number;
  supplier_price: number;
  supplier_url: string;
  supplier_name: string;
  profit: number;
  margin: number;
  verdict: string;
  is_read: boolean;
  found_at?: string | null;
}

// ── Dashboard ───────────────────────────────────────────────────

export interface Kpis {
  total_revenue: number;
  total_profit: number;
  avg_margin: number;
  total_sales: number;
  total_units: number;
  best_product: string;
  best_category: string;
  growth_revenue: number;
  growth_profit: number;
  days: number;
  error?: string;
}

export interface TrendChart {
  dates: string[];
  values: number[];
  total: number;
}

export interface CategoryBreakdown {
  categories: string[];
  values: number[];
}

export interface MonthlyComparison {
  labels: string[];
  revenue: number[];
  profit: number[];
}

export interface TopItem {
  product_name?: string;
  category?: string;
  total_revenue: number;
  total_profit: number;
  total_units: number;
}

export interface Sale {
  id: number;
  product_name: string;
  category: string;
  sale_price: number;
  supplier_cost: number;
  shipping_cost: number;
  ebay_fees: number;
  profit: number;
  margin_percent: number;
  quantity: number;
  sale_date?: string | null;
  buyer_location: string;
  notes: string;
}

// ── History ─────────────────────────────────────────────────────

export interface HistoryItem {
  id: number;
  title: string;
  price?: number | null;
  url?: string;
  image_url?: string | null;
  verdict?: string | null;
  profit?: number | null;
  margin?: number | null;
  created_at: string;
  outside_band?: boolean;
}

export interface HistoryListResponse {
  products: HistoryItem[];
  count: number;
  range_filter: PriceRange;
}

export interface ProductDetail {
  product: {
    id: number;
    title: string;
    price: number;
    condition: string;
    format: string;
    seller?: string;
    image_url?: string;
    category?: string;
    ebay_url: string;
    created_at?: string;
    updated_at?: string;
    outside_band?: boolean;
    provenance?: string;
    provenance_label?: string;
  };
  demand: DemandData | null;
  provenance?: string;
  provenance_label?: string;
  suppliers: {
    supplier_name: string;
    supplier_url?: string;
    supplier_title?: string;
    supplier_price?: number;
    delivery_days_min?: number;
    delivery_days_max?: number;
    provenance?: string;
    provenance_label?: string;
    source_url?: string;
    source_name?: string;
    match_basis?: string;
  }[];
  analysis: LLMAnalysis | null;
  verdict: {
    verdict: string;
    profit_amount?: number;
    profit_margin?: number;
    filter_results?: FilterCheck[] | string;
    scorecard?: string;
  } | null;
}
