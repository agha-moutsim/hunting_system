/**
 * Phase F - the title helper's client plumbing.
 *
 * The counts come from `/api/titles`, which counts the listings eBay actually
 * returned for the query. Nothing here estimates, re-ranks or extrapolates
 * them: this file shapes the request, slices the top rows for display, and
 * counts characters for eBay's 80-character title limit.
 */

import { apiFetch } from "./api";
import type { TitleCountsResponse } from "./types";

/** eBay UK's title limit, and the denominator the meter shows. */
export const TITLE_MAX_CHARS = 80;

/**
 * The most listings one Browse search returns to the helper: the API's
 * default and its ceiling. The page names this sample rather than implying it
 * read every matching title on eBay.
 */
export const TITLE_SAMPLE_LIMIT = 50;

export interface TitleQuery {
  q: string;
  limit?: number;
}

/** The request path, built once so tests can pin exactly what is asked. */
export function titlesPath(query: TitleQuery): string {
  const params = new URLSearchParams();
  params.set("q", query.q.trim());
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  return `/api/titles?${params.toString()}`;
}

export function fetchTitleCounts(
  query: TitleQuery
): Promise<TitleCountsResponse> {
  return apiFetch<TitleCountsResponse>(titlesPath(query));
}

/**
 * Count characters, not UTF-16 code units, so one emoji is one character.
 * The server counts titles; this only measures the title being written.
 */
export function titleLength(value: string): number {
  return Array.from(value).length;
}

export type TitleLimitState = "ok" | "over";

export function titleLimitState(length: number): TitleLimitState {
  return Number.isFinite(length) && length > TITLE_MAX_CHARS ? "over" : "ok";
}

export function titleMeterLabel(length: number): string {
  const safe = Number.isFinite(length) ? length : 0;
  return `${safe} / ${TITLE_MAX_CHARS}`;
}

/** Bar width, capped at 100% so an over-limit title cannot overflow the rail. */
export function titleMeterPercent(length: number): number {
  if (!Number.isFinite(length) || length <= 0) return 0;
  return Math.min(100, (length / TITLE_MAX_CHARS) * 100);
}

/** The first `limit` rows, preserving the server's count-first ordering. */
export function topTitleTerms<T>(rows: T[], limit = 10): T[] {
  return rows.slice(0, Math.max(0, limit));
}
