/**
 * Store link presentation — REGRESSION-007.
 *
 * eBay has two identifiers and the UI used to blur them:
 *
 *   /str/{slug}      a storefront. Only real when we OBSERVED that href.
 *   /usr/{username}  a seller profile. Always real, never a shop.
 *
 * The backend already decided which one a row has (`url_kind`). This module
 * turns that decision into exactly one label, so a row can never claim a
 * confirmed storefront on a link that was never confirmed.
 *
 * Pure and dependency-free so it can be unit tested without a DOM — the
 * project has no component-test renderer installed and adding one for this
 * would be a dependency the fix does not justify.
 */

export type StoreLinkKind = "observed" | "seller_profile";

export interface StoreLinkView {
  href: string;
  kind: StoreLinkKind;
  /** Short chip shown beside the seller name. */
  kindLabel: string;
  /** Tooltip text: where this link came from. */
  explanation: string;
  /** True ONLY for a storefront href read off an eBay page. */
  isConfirmedStorefront: boolean;
  /** Backend-supplied reason, when the row carries one. */
  reason?: string;
}

type StoreLike = {
  name?: string;
  url?: string | null;
  url_kind?: string | null;
  url_derived?: boolean;
  provenance?: string | null;
  provenance_reason?: string | null;
};

const EBAY_HOST = "ebay.co.uk";

function isEbayHost(href: string): boolean {
  try {
    return new URL(href).hostname.endsWith(EBAY_HOST);
  } catch {
    return false;
  }
}

/**
 * Resolve what a store row's link actually is.
 *
 * Returns null when there is nothing safe to link to, so the caller renders
 * the name as plain text rather than emitting a dead `href="#"` (REGRESSION-007).
 */
export function describeStoreLink(
  store: StoreLike | null | undefined
): StoreLinkView | null {
  const href = (store?.url ?? "").trim();
  if (!href || href === "#") return null;
  if (!/^https?:\/\//i.test(href)) return null;

  const onEbay = isEbayHost(href);
  const hasStorePath = /\/str\//.test(href);
  const hasProfilePath = /\/usr\//.test(href);

  // Prefer the backend's decision; fall back to reading the URL for rows
  // persisted before `url_kind` existed.
  let kind: StoreLinkKind;
  if (store?.url_kind === "observed" || store?.url_kind === "seller_profile") {
    kind = store.url_kind;
  } else if (hasStorePath) {
    kind = "observed";
  } else {
    kind = "seller_profile";
  }

  // An off-eBay or malformed href can never stand as a verified storefront,
  // whatever the row claims.
  const isConfirmedStorefront = kind === "observed" && hasStorePath && onEbay;

  const view: StoreLinkView = {
    href,
    kind: isConfirmedStorefront ? "observed" : "seller_profile",
    kindLabel: isConfirmedStorefront ? "Store" : "Seller profile",
    explanation: isConfirmedStorefront
      ? "Storefront link observed directly on this eBay listing."
      : hasProfilePath
        ? "eBay seller profile — this is the seller's account page, not their shop."
        : "Link is not a confirmed eBay storefront.",
    isConfirmedStorefront,
  };

  const reason = store?.provenance_reason?.trim();
  if (reason) view.reason = reason;
  return view;
}
