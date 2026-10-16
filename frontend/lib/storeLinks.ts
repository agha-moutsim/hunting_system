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

/**
 * What the backend's verification concluded about an observed storefront.
 * `null` means the row predates verification, or was never checked.
 */
export type StoreCheckState = "verified" | "not_found" | "unavailable" | null;

export interface StoreLinkView {
  /** null when there is nowhere safe to go — a dead store, or no link. */
  href: string | null;
  kind: StoreLinkKind;
  /** Short chip shown beside the seller name. */
  kindLabel: string;
  /** Tooltip text: where this link came from, and what we know about it. */
  explanation: string;
  /** True ONLY when eBay itself confirmed the storefront exists. */
  isConfirmedStorefront: boolean;
  /** True when eBay answered, and there is no shop at that URL. */
  isDeadStore: boolean;
  /** The backend's verdict, when one was recorded. */
  storeCheck: StoreCheckState;
  /** Backend-supplied reason, when the row carries one. */
  reason?: string;
}

type StoreLike = {
  name?: string;
  url?: string | null;
  url_kind?: string | null;
  url_derived?: boolean;
  store_check?: string | null;
  store_check_reason?: string | null;
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
  const rawHref = (store?.url ?? "").trim();
  if (!rawHref || rawHref === "#") return null;
  if (!/^https?:\/\//i.test(rawHref)) return null;

  const onEbay = isEbayHost(rawHref);
  const hasStorePath = /\/str\//.test(rawHref);
  const hasProfilePath = /\/usr\//.test(rawHref);

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

  const rawCheck = (store?.store_check ?? "").trim();
  const storeCheck: StoreCheckState =
    rawCheck === "verified" ||
    rawCheck === "not_found" ||
    rawCheck === "unavailable"
      ? rawCheck
      : null;

  // An off-eBay or malformed href can never stand as a verified storefront,
  // whatever the row claims.
  const isStoreLink = kind === "observed" && hasStorePath && onEbay;
  const isDeadStore = isStoreLink && storeCheck === "not_found";
  // Only eBay saying so makes a storefront CONFIRMED. An observed href that
  // nobody checked is still just an observation.
  const isConfirmedStorefront = isStoreLink && storeCheck === "verified";

  let kindLabel: string;
  let explanation: string;
  if (isDeadStore) {
    kindLabel = "Store not found";
    explanation =
      "eBay answered for this storefront and reports no shop at this address.";
  } else if (isConfirmedStorefront) {
    kindLabel = "Store";
    explanation =
      "Storefront link read from this eBay listing and confirmed by eBay.";
  } else if (storeCheck === "unavailable" && isStoreLink) {
    kindLabel = "Store (unchecked)";
    explanation =
      "This storefront link could not be checked — the result is unknown, not confirmed.";
  } else if (isStoreLink) {
    kindLabel = "Store (unchecked)";
    explanation =
      "Storefront link read from this eBay listing; not yet verified.";
  } else if (hasProfilePath) {
    kindLabel = "Seller profile";
    explanation =
      "eBay seller profile — this is the seller's account page, not their shop.";
  } else {
    kindLabel = "Seller profile";
    explanation = "Link is not a confirmed eBay storefront.";
  }

  const view: StoreLinkView = {
    // A store eBay has denied is not somewhere to send anyone.
    href: isDeadStore ? null : rawHref,
    kind: isStoreLink ? "observed" : "seller_profile",
    kindLabel,
    explanation,
    isConfirmedStorefront,
    isDeadStore,
    storeCheck,
  };

  // Prefer the verification reason; fall back to the row's own provenance note.
  const reason =
    store?.provenance_reason?.trim() || store?.store_check_reason?.trim();
  if (reason) view.reason = reason;
  return view;
}
