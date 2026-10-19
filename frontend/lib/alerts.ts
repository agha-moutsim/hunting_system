/**
 * Phase E - the alerts inbox's client plumbing.
 *
 * The comparison lives on the server (hunter/alerts.py): a row exists only
 * when two real readings were compared, and its message is the sentence that
 * comparison earned. Nothing here re-derives a price or a margin - it shapes
 * filters into the request and formats the two stored values for display.
 *
 * One subtlety the row type carries: `old_price`/`new_price` are money for
 * price rows and margin percentages for margin rows. The unit is decided by
 * `alert_type`, never guessed from the number, so a 33.5 can never be shown
 * as GBP 33.50.
 *
 * The "New matches" lane is saved-search results (a different table, written
 * only for a result that passed its search's own band and minimum margin),
 * surfaced through the same page. Its functions live here so the inbox has
 * one client surface.
 */

import { apiFetch, apiPost } from "./api";
import { formatGBP } from "./format";
import type {
  AlertCountResponse,
  AlertListResponse,
  AlertReadResponse,
  NewMatchesResponse,
  SavedSearchListResponse,
  SearchRunResponse,
  PriceAlert,
} from "./types";

// ── Tabs ────────────────────────────────────────────────────────

export type AlertTabKey = "all" | "price" | "margin" | "matches";

export interface AlertTab {
  key: AlertTabKey;
  label: string;
  /** alert_type query value; null = every kind. */
  alertType: string | null;
  /** This tab reads saved-search results, not price-alert rows. */
  readsMatches?: boolean;
}

/**
 * The tabs the design calls for. "Price" covers every row about an item's
 * own price - both directions and target hits - because those three read the
 * same way (money compared to money); margin rows are percentages and get
 * their own tab.
 */
export const ALERT_TABS: AlertTab[] = [
  { key: "all", label: "All", alertType: null },
  {
    key: "price",
    label: "Price",
    alertType: "price_drop,price_increase,target_hit",
  },
  { key: "margin", label: "Margin", alertType: "margin_alert" },
  { key: "matches", label: "New matches", alertType: null, readsMatches: true },
];

// ── Alerts ──────────────────────────────────────────────────────

export interface AlertQuery {
  unreadOnly?: boolean;
  alertType?: string | null;
  limit?: number;
  offset?: number;
}

/** The request path, built once so tests can pin exactly what is asked. */
export function alertsPath(query: AlertQuery = {}): string {
  const params = new URLSearchParams();
  if (query.unreadOnly) params.set("unread_only", "true");
  if (query.alertType) params.set("alert_type", query.alertType);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  const qs = params.toString();
  return qs ? `/api/alerts?${qs}` : "/api/alerts";
}

export function fetchAlerts(
  query: AlertQuery = {}
): Promise<AlertListResponse> {
  return apiFetch<AlertListResponse>(alertsPath(query));
}

export function fetchAlertCount(): Promise<AlertCountResponse> {
  return apiFetch<AlertCountResponse>("/api/alerts/count");
}

export function markAlertRead(id: number): Promise<AlertReadResponse> {
  return apiPost<AlertReadResponse>(`/api/alerts/${id}/read`, {});
}

export function markAllAlertsRead(): Promise<AlertReadResponse> {
  return apiPost<AlertReadResponse>("/api/alerts/read-all", {});
}

// ── Display: the unit is the row's, not a guess ─────────────────

export type AlertUnit = "margin" | "price";

export function alertUnit(alertType: string): AlertUnit {
  return alertType === "margin_alert" ? "margin" : "price";
}

export function formatAlertValue(
  value: number | null | undefined,
  unit: AlertUnit
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return unit === "margin" ? `${value.toFixed(1)}%` : formatGBP(value);
}

/**
 * The two values the row compared, in the row's own unit. Margin rows were
 * stored with the two margins (the prices they came from are in the
 * sentence), so this must not render them as pounds.
 */
export function formatAlertPair(alert: {
  alert_type: string;
  old_price: number | null;
  new_price: number | null;
}): string {
  const unit = alertUnit(alert.alert_type);
  return `${formatAlertValue(alert.old_price, unit)} → ${formatAlertValue(
    alert.new_price,
    unit
  )}`;
}

export function alertTypeLabel(alertType: string): string {
  switch (alertType) {
    case "price_drop":
      return "Price drop";
    case "price_increase":
      return "Price rise";
    case "target_hit":
      return "Target hit";
    case "margin_alert":
      return "Margin";
    default:
      return "Alert";
  }
}

/** Sidebar badge text: nothing at zero, capped so it cannot stretch the nav. */
export function unreadBadge(count: number): string | null {
  if (!Number.isFinite(count) || count <= 0) return null;
  return count > 99 ? "99+" : String(count);
}

/** Rows that still need attention - used to keep the inbox's count honest. */
export function unreadAlerts(alerts: PriceAlert[]): PriceAlert[] {
  return alerts.filter((alert) => !alert.is_read);
}

// ── New matches: saved-search results in the same inbox ─────────

export function fetchSavedSearches(): Promise<SavedSearchListResponse> {
  return apiFetch<SavedSearchListResponse>("/api/searches");
}

export function fetchNewMatches(
  unreadOnly = false,
  limit = 50
): Promise<NewMatchesResponse> {
  const params = new URLSearchParams();
  params.set("unread_only", unreadOnly ? "true" : "false");
  params.set("limit", String(limit));
  return apiFetch<NewMatchesResponse>(`/api/searches/results?${params}`);
}

/**
 * Run one saved search. This is the only action on the page that spends
 * Browse quota; the response states the cost (`browse_calls`) and, when
 * nothing was stored, the reason the runner gave.
 */
export function runSavedSearch(id: number): Promise<SearchRunResponse> {
  return apiPost<SearchRunResponse>(`/api/searches/${id}/run`, {});
}

export function markMatchRead(id: number): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/api/searches/results/${id}/read`, {});
}
