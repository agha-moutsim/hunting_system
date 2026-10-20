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
  /**
   * REGRESSION-007: which eBay identifier this link is.
   * "observed" = a /str/ storefront href read off an eBay page.
   * "seller_profile" = /usr/ profile, derived from a real username.
   * A username is NOT a store slug, so /str/ is never synthesised from one.
   */
  url_kind?: "observed" | "seller_profile";
  /** true = the URL was built from the username, never observed. */
  url_derived?: boolean;
  /**
   * What eBay said when the backend checked this storefront.
   * "verified" | "not_found" | "unavailable". Absent on rows saved before
   * verification existed, or when no verification key is configured.
   */
  store_check?: "verified" | "not_found" | "unavailable";
  store_check_reason?: string;
  /** Listings observed in the search window (cap 50) - NOT eBay sold count. */
  sold_count: number;
  sold_count_label?: string;
  avg_price: number;
  provenance?: string;
  provenance_label?: string;
  /** Why a row is not a confirmed storefront, when it is not. */
  provenance_reason?: string;
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
  /**
   * How the row was obtained (C13): "api" = a credentialed API response,
   * "browser" = read off a live page by Playwright, ""/absent = not stated.
   * Absent is unknown, never a claim that it came from an API.
   */
  fetch_method?: string;
  /** True when this price sits outside the active price range. */
  outside_band?: boolean;
}

/**
 * PHASE C — one measured number plus the two facts that make it checkable.
 *
 * `origin` names WHAT produced the number, as a token the backend owns
 * (api/schemas.py). `observed_at` is when that source observed it, which is not
 * when the analysis ran: a purchase-history capture can be a day old, and a
 * screen saying "just now" about it would be the same class of error as
 * counting a live listing as a sale.
 *
 * `value` null means "not read" — never 0, because 0 is a real measurement.
 */
export interface SourcedFigure {
  value?: number | null;
  origin?: string | null;
  observed_at?: string | null;
}

export interface DemandData {
  sold_count_30d?: number | null;
  sold_count_7d?: number | null;
  last_sale_date?: string | null;
  avg_sold_price?: number | null;
  lowest_sold_price?: number | null;
  highest_sold_price?: number | null;
  /**
   * Every individual SALE price observed. The source of the min/avg/max above
   * — carried rather than re-derived so the chart plots exactly the figures
   * the metrics show. Absent/empty on rows saved before it existed: no chart,
   * never a fabricated one. A live listing's asking price never lands here.
   */
  sold_prices?: number[] | null;
  /**
   * SUPPLY, not demand: the in-band New listings eBay is showing right now,
   * and their ASKING prices. Real numbers from a real fetch, and not evidence
   * that anything sold — which is why they have their own fields instead of
   * sharing the sold ones, as they did until 2026-10-19.
   */
  active_listings_in_band?: number | null;
  avg_active_price?: number | null;
  lowest_active_price?: number | null;
  highest_active_price?: number | null;
  /** The asking prices behind those figures, same discipline as sold_prices. */
  active_prices?: number[] | null;
  /**
   * The sentence the analysis wrote when it stored the row: which query
   * produced these figures, and the source of any sold figure that did not
   * come from that query. The endpoint carried it all along and this type did
   * not, so the Sources view could not read a sentence the API was already
   * sending.
   */
  data_source?: string | null;
  verified?: boolean;
  provenance?: string;
  provenance_label?: string;
  /**
   * PHASE C — the sold figures with their provenance attached, keyed by figure.
   *
   * Absent or null means the figure was never measured. It is never 0, and
   * never a figure carrying a label borrowed from a neighbouring field: 0 is a
   * real count, and an origin badge over a number nobody read is worse than no
   * badge at all. The flat `sold_count_*` keys above are unchanged for readers
   * that predate this block.
   */
  figures?: {
    sold_count_7d?: SourcedFigure | null;
    sold_count_30d?: SourcedFigure | null;
  } | null;
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
  /** Per-sale prices behind the price summary. Empty when the run held
   *  none — the chart draws its honest empty state, never a stand-in. */
  sold_prices: number[];
  /** ASKING prices of the live listings, for the runs where THAT is what the
   *  scrape returned. Real prices, supply-side meaning: the chart names which
   *  list it drew rather than calling every bar a sale. */
  active_prices: number[];
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
  /**
   * Windowed hot signals. A 7d hot decision uses ONLY a real 7d capture;
   * when that capture is absent the field is "unverified" with a reason -
   * never a 30d number dressed up as a week.
   */
  hot_7d?: boolean;
  hot_7d_basis?: string;
  hot_7d_provenance?: "verified" | "unverified";
  hot_7d_reason?: string;
  hot_30d?: boolean;
  hot_30d_basis?: string;
  hot_30d_provenance?: "verified" | "unverified";
  hot_30d_reason?: string;
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

export interface AlertListResponse {
  alerts: PriceAlert[];
  count: number;
  total: number;
  unread: number;
}

export interface AlertCountResponse {
  unread: number;
}

export interface AlertReadResponse {
  ok: boolean;
  unread: number;
  /** Present on /alerts/read-all: how many rows the call flipped. */
  marked?: number;
}

export interface SavedSearchListResponse {
  searches: SavedSearch[];
}

export interface NewMatchesResponse {
  results: SearchResult[];
  unread_count: number;
  range_filter: PriceRange;
}

/** POST /api/searches/{id}/run - what one saved-search run did, and cost. */
export interface SearchRunResponse {
  found: number;
  error: string | null;
  reason: string | null;
  browse_calls: number;
}

/** POST /api/searches/run-all - a pass with its stated Browse budget. */
export interface SearchPassResponse {
  searches_run: number;
  searches_stored: number;
  searches_not_run: number;
  total_found: number;
  browse_calls: number;
  reasons: string[];
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
    provenance?: string | null;
    provenance_label?: string | null;
    /** C13 — replayed alongside provenance; absent on pre-2026-10-06 rows. */
    verified?: boolean | null;
    /** C13 — "api" / "browser" / null when the row never stated it. */
    fetch_method?: string | null;
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

// ---------------------------------------------------------------------------
// Deals board.
//
// Every field traces to eBay: either its own curated deals page, or the Browse
// API keyed by that card's listing id. There is deliberately NO sold count and
// NO popularity figure, because neither is measurable from this app — see
// backend/scrapers/ebay_deals.py for the list of sources that were tried and
// rejected before this board was built this way.
// ---------------------------------------------------------------------------

export interface DealItem {
  listing_id: string;
  title: string;
  image_url: string;
  item_url: string;
  /** Real price read from the Browse API, or null when it could not be read. */
  price: number | null;
  currency: string;
  /** Pre-formatted, and "" when the price was not read. Never "£0.00". */
  price_label: string;
  price_read: boolean;
  seller: string;
  store_name: string;
  store_url: string;
  /** True only for a storefront link eBay itself rendered. */
  store_verified: boolean;
  condition: string;
  /** Position on eBay's own page — an observation, never a rank by sales. */
  position: number;
  source: string;
  source_label: string;
  fetched_at: string;
}

export interface DealsMeta {
  total: number;
  priced: number;
  unpriced: number;
  last_fetched: string;
  /** Seconds since the last refresh, or null when one has never run. */
  age_seconds: number | null;
  stale: boolean;
  refresh_interval_seconds: number;
  source: string;
  source_label: string;
  auto_refresh: boolean;
  refresh_started?: boolean;
}

export interface DealsResponse {
  meta: DealsMeta;
  count: number;
  items: DealItem[];
}

/**
 * PHASE C — one line of the Sources view.
 *
 * `value` null is the load-bearing case: it means the field was never
 * measured, and the view's "not known" list is derived from exactly those
 * rows. `unknownReason` says what it would take to know, and is rendered only
 * against a null value — it can never be attached to a figure that exists.
 */
export interface SourceRow {
  /** The payload key, so a figure can be found in the API and the database. */
  name: string;
  /** What the figure means, for a reader who has never seen the API. */
  label: string;
  /** The rendered value, or null when nothing was measured for this field. */
  value: string | null;
  /** Where it came from, when the backend recorded an origin. */
  stamp?: ProvenanceInfo | null;
  /** When the source read it, already formatted; null when not recorded. */
  readAt?: string | null;
  /** What it would take to know this. Rendered only for a null value. */
  unknownReason: string;
  /** True for a count of live listings: real, and not evidence of a sale. */
  supply?: boolean;
}

// ── Phase D - fee calculator ───────────────────────────────────

/** The table that made a figure: key, dated version, currency. */
export interface FeeTableRef {
  key: string;
  version: string;
  currency: string;
}

/** One itemised line, exactly as the engine states it. */
export interface FeeLine {
  label: string;
  /** The table's rate text ("12.9%", "0.35%", "20%"), or null. */
  rate: string | null;
  amount: number;
}

export interface FeeCategoryInfo {
  key: string;
  name: string;
  /** False when the engine fell back to its stated default. */
  known: boolean;
  category_ids?: number[];
  rate_applied?: string;
  assumption?: string | null;
}

export interface FeeCalculationFees {
  fee_table: FeeTableRef;
  seller: {
    type: string;
    uk_resident?: boolean | null;
    vat_registered?: boolean | null;
  };
  buyer_region: string;
  category: FeeCategoryInfo | null;
  fee_basis: string;
  total_amount_of_sale: number;
  fvf: number;
  fvf_rate: string;
  per_order_fee: number | null;
  regulatory_fee: number | null;
  international_fee: number | null;
  promoted_fee: number | null;
  listing_fee: number | null;
  vat_on_fees: number | null;
  vat_recoverable: boolean;
  vat_note?: string | null;
  fees_quoted_total: number;
  fees_cost_total: number;
  assumptions: string[];
  notes: string[];
  ok: boolean;
}

/** The engine's whole money view of one sale. */
export interface FeeCalculation {
  ok: boolean;
  fee_lines: FeeLine[];
  fees: FeeCalculationFees;
  price: number;
  postage_charged: number;
  proceeds: number;
  supplier_cost: number | null;
  /** The seller's own postage; 0 means UNKNOWN, not free. */
  postage_paid: number;
  postage_paid_known: boolean;
  risk_buffer_percent: number;
  risk_buffer: number;
  packaging_cost: number;
  net_after_fees: number;
  profit: number | null;
  margin: number | null;
  profit_is_complete: boolean;
  profit_missing_reason?: string | null;
}

export interface FeeCategory {
  key: string;
  name: string;
  category_ids: number[];
  rate_label: string;
  notes: string[];
}

export interface FeeSource {
  label: string;
  url: string;
  page_updated: string;
  retrieved: string;
}

export interface FeeTable {
  key: string;
  version: string;
  currency: string;
  vat_rate: number;
  sources: FeeSource[];
  business: Record<string, unknown>;
  private: Record<string, unknown>;
}

export interface SellerProfile {
  seller_type: "business" | "private";
  uk_resident: boolean;
  vat_registered: boolean;
  promoted_rate: number;
  category: string | null;
  fee_table: string | null;
}

export interface FeeTableResponse {
  fee_table: FeeTable;
  categories: FeeCategory[];
  profile: SellerProfile;
}

export type FeeBuyerRegion =
  "uk" | "eu_northern_europe" | "us_canada" | "rest_of_world";

export interface FeeCalculateRequest {
  sale_price?: number | null;
  target_margin?: number | null;
  postage_charged?: number;
  postage_paid?: number;
  category?: string | null;
  promoted_rate?: number | null;
  seller_type?: "business" | "private" | null;
  uk_resident?: boolean | null;
  vat_registered?: boolean | null;
  listing_fee?: number;
  buyer_region?: FeeBuyerRegion;
  fee_table?: string | null;
  supplier_cost?: number | null;
  risk_buffer_percent?: number | null;
  packaging_cost?: number | null;
}

export interface FeeSolveCheck {
  price: number;
  profit: number;
  margin: number;
  fees_cost_total: number;
  net_after_fees: number;
}

export interface FeeForwardResult {
  mode: "forward";
  fee_table: FeeTableRef;
  calculation: FeeCalculation;
}

export interface FeeReverseResult {
  mode: "reverse";
  fee_table: FeeTableRef;
  achievable: boolean;
  price: number | null;
  target_margin: number;
  reason: string | null;
  check: FeeSolveCheck | null;
  /** The same money view at the solved price, when one was found. */
  calculation?: FeeCalculation;
}

export type FeeCalculateResponse = FeeForwardResult | FeeReverseResult;

// ── Phase F: title helper ───────────────────────────────────────

/** One word and the number of listings whose title contained it. */
export interface TitleWordCount {
  word: string;
  count: number;
}

/** One adjacent pair and the number of listings whose title contained it. */
export interface TitlePhraseCount {
  phrase: string;
  count: number;
}

/**
 * Counts over the listings eBay actually returned for the query.
 *
 * `listings_analysed` is the sample size and is always present. There is no
 * search-volume field: eBay gives this app no such figure, and the tables
 * are measurements of the sample, not an estimate of demand.
 */
export interface TitleCountsResponse {
  query: string;
  listings_analysed: number;
  unigrams: TitleWordCount[];
  bigrams: TitlePhraseCount[];
  /** A sentence when the sample is empty; null when there are counts. */
  reason: string | null;
}

// ── Phase G: listing age and churn ─────────────────────────────

/**
 * Age read from eBay's own `itemCreationDate`.
 *
 * `days` is whole days, floored. `tone` is presentation only. The label is
 * built in lib/churn.ts, so the UI copy exists in one place. There is no
 * first-sighting fallback here: the API returns null when eBay did not give a
 * creation date, and the chip says "first seen", never "listed".
 */
export interface ListingAgeInfo {
  days: number;
  tone: "info" | "neutral";
  basis: string;
}

export interface ListingAgeResponse {
  listing_id: string;
  observed: boolean;
  readings: number;
  /** The first stored reading for this listing. */
  first_seen_at: string | null;
  /** The latest stored reading, which is a change time, not a last-seen time. */
  latest_reading_at: string | null;
  item_creation_date: string | null;
  age: ListingAgeInfo | null;
  /** A sentence when age is not claimed; null when it is. */
  reason: string | null;
}

/**
 * One row from a stored search result set.
 *
 * `age` is present on the latest-observation rows and absent on churned rows;
 * a churned row carries `status` instead. Price is null when eBay did not
 * return it and is never defaulted to zero.
 */
export interface ChurnListing {
  listing_id: string;
  title: string | null;
  item_url: string | null;
  price: number | null;
  currency: string | null;
  item_creation_date: string | null;
  /** First stored search set in this query lane that contained it. */
  first_seen_at: string | null;
  /** Last stored search set in this query lane that contained it. */
  last_seen_at: string | null;
  age?: ListingAgeInfo | null;
  age_reason?: string | null;
  status?: "no_longer_listed";
}

/**
 * One query's stored observation comparison.
 *
 * `churned` is null when churn is not claimed: fewer than two observations,
 * or observations whose filters/sample sizes differ. An empty array is a
 * measured comparison with no missing listing and is not the same thing.
 * There is no rate or percentage field because this app has no basis for one.
 */
export interface ChurnResponse {
  query: string;
  observations: number;
  comparable: boolean;
  latest_observed_at: string | null;
  previous_observed_at: string | null;
  earliest_observed_at: string | null;
  latest_listing_count: number;
  earlier_listing_count: number;
  /** The exact filter behind the latest sample, or null when absent. */
  filter: string | null;
  /** The sample ceiling sent for the latest observation, or null. */
  limit: number | null;
  latest: ChurnListing[];
  churned: ChurnListing[] | null;
  reason: string | null;
}
