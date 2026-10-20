/**
 * The selected marketplace, stored where every client request can read it.
 *
 * Kept out of `lib/marketplace.ts` so `lib/api.ts` can import the synchronous
 * getter without importing React or creating a cycle with `apiFetch`.
 */

export const DEFAULT_MARKETPLACE_ID = "EBAY_GB";
export const MARKETPLACE_STORAGE_KEY = "ebayhunter.marketplace";
export const MARKETPLACE_CHANGE_EVENT = "ebayhunter:marketplacechange";
export const MARKETPLACE_HEADER = "X-EBay-Marketplace";

/** The stored id, or the historical UK default on the server / first visit. */
export function getMarketplaceId(): string {
  if (typeof window === "undefined") return DEFAULT_MARKETPLACE_ID;
  try {
    return (
      window.localStorage.getItem(MARKETPLACE_STORAGE_KEY)?.trim() ||
      DEFAULT_MARKETPLACE_ID
    );
  } catch {
    // Private mode or a blocked storage API: the default still works.
    return DEFAULT_MARKETPLACE_ID;
  }
}

/** Persist a selection and tell every mounted surface to re-read it. */
export function setMarketplaceId(id: string): void {
  if (typeof window === "undefined") return;
  const next = id.trim() || DEFAULT_MARKETPLACE_ID;
  try {
    window.localStorage.setItem(MARKETPLACE_STORAGE_KEY, next);
  } catch {
    /* the in-page event below still updates this tab */
  }
  window.dispatchEvent(
    new CustomEvent(MARKETPLACE_CHANGE_EVENT, { detail: next })
  );
}

/** Subscribe to in-tab selections and cross-tab storage changes. */
export function subscribeMarketplace(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key === MARKETPLACE_STORAGE_KEY) listener();
  };
  window.addEventListener(MARKETPLACE_CHANGE_EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(MARKETPLACE_CHANGE_EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Header sent on every API call. */
export function marketplaceHeaders(): Record<string, string> {
  return { [MARKETPLACE_HEADER]: getMarketplaceId() };
}
