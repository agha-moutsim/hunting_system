/**
 * Phase H - seller footprint client plumbing.
 *
 * The API returns eBay's feedback numbers, item-location parts and counts
 * over observed listings. This file turns them into the labels the design
 * permits. It never computes a seller score, a sale, a rate or a revenue
 * figure; a missing value stays "Not stated".
 *
 * Every aggregate keeps the sample size it came from. The page is where the
 * sample and the "observed active listings" caveat are put beside the
 * numbers; these helpers only format what the API measured.
 */

import { apiFetch } from "./api";
import type { SellerFootprintResponse, SellerPriceStats } from "./types";

/**
 * The required boundary of the panel's claim.
 *
 * Kept in one place so the component, the test and any future surface cannot
 * drift into a stronger statement. The page renders this exact sentence.
 */
export const SELLER_DISCLAIMER =
  "Observed active listings. Nothing here measures what this seller has actually sold.";

/** The read-only seller path, with an optional query lane. */
export function sellerPath(username: string, query?: string | null): string {
  const name = username.trim();
  const path = `/api/sellers/${encodeURIComponent(name)}`;
  const key = (query || "").trim();
  if (!key) return path;
  const params = new URLSearchParams();
  params.set("query", key);
  return `${path}?${params.toString()}`;
}

/** The Next.js page path for a seller, used by links into the panel. */
export function sellerPagePath(
  username: string,
  query?: string | null
): string {
  const name = username.trim();
  const path = `/sellers/${encodeURIComponent(name)}`;
  const key = (query || "").trim();
  if (!key) return path;
  const params = new URLSearchParams();
  params.set("query", key);
  return `${path}?${params.toString()}`;
}

export function fetchSeller(
  username: string,
  query?: string | null,
  signal?: AbortSignal
): Promise<SellerFootprintResponse> {
  return apiFetch<SellerFootprintResponse>(sellerPath(username, query), {
    signal,
  });
}

function finite(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

/**
 * eBay's feedback percentage, with at most two decimals.
 *
 * The raw value is kept as a number by the API; this only removes trailing
 * zeroes. A null is null, never "0%".
 */
export function formatFeedbackPercentage(
  value: number | null | undefined
): string | null {
  if (!finite(value)) return null;
  const text = value.toFixed(2).replace(/\.?0+$/, "");
  return `${text}%`;
}

/** eBay's feedback score with thousands separators; null stays null. */
export function formatFeedbackScore(
  value: number | null | undefined
): string | null {
  if (!finite(value)) return null;
  return Math.trunc(value).toLocaleString("en-GB");
}

/**
 * The feedback line: percentage and score from the same reading.
 *
 * When only one is present the line shows only that one. It never invents a
 * missing score or percentage.
 */
export function formatFeedback(
  percentage: number | null | undefined,
  score: number | null | undefined
): string | null {
  const pct = formatFeedbackPercentage(percentage);
  const count = formatFeedbackScore(score);
  if (pct && count) return `${pct} (${count})`;
  if (pct) return pct;
  if (count) return count;
  return null;
}

/**
 * Item location as eBay returned it: country and postal code together.
 *
 * This is the item location, not an inference about where the seller lives.
 */
export function formatSellerRegion(
  country: string | null | undefined,
  postalCode: string | null | undefined
): string | null {
  const nation = (country || "").trim();
  const postal = (postalCode || "").trim();
  if (nation && postal) return `${nation} - ${postal}`;
  return nation || postal || null;
}

function formatShare(share: number): string {
  const rounded = Math.round(share * 1000) / 10;
  return `${rounded.toFixed(1).replace(/\.0$/, "")}%`;
}

/**
 * Condition mix over the listings whose condition was actually read.
 *
 * The API's `known` denominator is what each share uses. When no condition
 * was read this returns null; the page then shows the API's reason rather
 * than an empty "0% New".
 */
export function formatConditionMix(
  values:
    { condition: string; count: number; share: number }[] | null | undefined
): string | null {
  if (!values || values.length === 0) return null;
  return values
    .filter((value) => finite(value.share) && value.condition)
    .map((value) => `${formatShare(value.share)} ${value.condition}`)
    .join(" · ");
}

function formatSellerMoney(
  amount: number,
  currency: string | null | undefined
): string {
  const code = (currency || "").trim();
  if (!code) return amount.toFixed(2);
  return `${code} ${amount.toFixed(2)}`;
}

/**
 * Asking range and median, one price per listing.
 *
 * The sample is not hidden: the caller renders it beside this line. A null
 * stats block means the API refused a range (often mixed currencies).
 */
export function formatPriceStats(
  stats: SellerPriceStats | null | undefined
): string | null {
  if (!stats) return null;
  const low = formatSellerMoney(stats.min, stats.currency);
  const high = formatSellerMoney(stats.max, stats.currency);
  if (stats.min === stats.max) return low;
  const middle = formatSellerMoney(stats.median, stats.currency);
  return `${low} - ${high}, median ${middle}`;
}

function dayLabel(days: number): string {
  return `${days} ${days === 1 ? "day" : "days"}`;
}

/** Age range from eBay creation dates, in whole days. */
export function formatAgeStats(
  stats:
    { min_days: number; max_days: number; sample: number } | null | undefined
): string | null {
  if (!stats) return null;
  if (stats.min_days === stats.max_days) return dayLabel(stats.min_days);
  return `between ${stats.min_days} and ${stats.max_days} days`;
}
