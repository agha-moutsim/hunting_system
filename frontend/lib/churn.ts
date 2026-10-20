/**
 * Phase G - listing age and churn client plumbing.
 *
 * The API returns measured days and stored timestamps. This file turns them
 * into the two labels the design permits: an age from eBay's own creation
 * date, or "first seen here" when eBay did not provide one. A listing that is
 * missing from the latest search sample says "no longer listed"; it never
 * says what happened to it.
 *
 * Nothing here estimates a rate or extrapolates from the sample. The counts
 * come from the API and are shown beside the sample size.
 */

import { apiFetch } from "./api";
import { formatDate, formatGBP } from "./format";
import type { ChurnResponse, ListingAgeResponse } from "./types";

/** The only status label for a listing missing from the latest sample. */
export const NO_LONGER_LISTED_LABEL = "NO LONGER LISTED";

/** The read-only churn path, built once so tests pin exactly what is asked. */
export function churnPath(query: string): string {
  const params = new URLSearchParams();
  params.set("query", query.trim());
  return `/api/observations/churn?${params.toString()}`;
}

/** One listing's age/readings path. */
export function listingObservationPath(listingId: string): string {
  return `/api/observations/${encodeURIComponent(listingId.trim())}`;
}

export function fetchChurn(
  query: string,
  signal?: AbortSignal
): Promise<ChurnResponse> {
  return apiFetch<ChurnResponse>(churnPath(query), { signal });
}

export function fetchListingAge(
  listingId: string,
  signal?: AbortSignal
): Promise<ListingAgeResponse> {
  return apiFetch<ListingAgeResponse>(listingObservationPath(listingId), {
    signal,
  });
}

/**
 * The age chip's label, from measured whole days.
 *
 * Null/negative/non-finite means no age claim. The component then falls back
 * to the first-sighting label, which is deliberately different copy.
 */
export function listingAgeLabel(
  days: number | null | undefined
): string | null {
  if (
    days === null ||
    days === undefined ||
    !Number.isFinite(days) ||
    days < 0
  ) {
    return null;
  }
  const whole = Math.floor(days);
  if (whole === 0) return "LISTED TODAY";
  if (whole === 1) return "LISTED 1 DAY AGO";
  return `LISTED ${whole} DAYS AGO`;
}

/** The status chip's last-seen line, or null when no run time is stored. */
export function lastSeenLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return `Last seen ${formatDate(iso)}`;
}

/** The secondary line under a real age chip. */
export function firstSeenLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return `First seen here ${formatDate(iso)}`;
}

/** The chip used when there is no eBay creation date: not an age claim. */
export function firstSeenChipLabel(
  iso: string | null | undefined
): string | null {
  if (!iso) return null;
  return `FIRST SEEN ${formatDate(iso).toUpperCase()}`;
}

/** True only when the API actually made a churn comparison. */
export function churnIsClaimable(result: ChurnResponse | null): boolean {
  return result !== null && result.churned !== null;
}

/**
 * A price from the snapshot. Null stays an em dash; a non-GBP currency shows
 * its code rather than putting a pound sign on a different currency.
 */
export function formatListingPrice(
  price: number | null | undefined,
  currency: string | null | undefined
): string {
  if (price === null || price === undefined || Number.isNaN(price)) return "—";
  if (currency && currency !== "GBP") {
    return `${price.toFixed(2)} ${currency}`;
  }
  return formatGBP(price);
}
