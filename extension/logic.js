// Pure decision logic for the sold-history capture extension.
//
// Deliberately free of chrome.* calls: background.js imports this as an ES
// module and the vitest suite imports the very same file, so every rule below
// is testable without a browser. The two rules that matter most are the ones
// that protect the user's eBay account - a per-item dedupe window and an
// absolute hourly cap - and a rule that cannot be tested is a rule that
// quietly stops working.

/** One capture per item per window. Six hours is far below what a person notices. */
export const DEDUPE_MS = 6 * 60 * 60 * 1000;

/**
 * Absolute ceiling on purchase-history requests per hour, counting attempts
 * rather than successes. Normal browsing never approaches this; it exists so
 * that a bug, a redirect loop or a compromised popup cannot turn the user's
 * signed-in session into a crawler.
 */
export const MAX_PER_HOUR = 60;

export const HOUR_MS = 60 * 60 * 1000;

/**
 * The whole persisted capture state — the contract background.js writes into
 * chrome.storage.local, spelled out once so it cannot drift silently.
 *
 * @typedef {object} CaptureState
 * @property {boolean} quiet          Nothing is captured at all, automatic or manual.
 * @property {Record<string, number>} lastCaptured itemId -> epoch ms of the last request.
 * @property {number} hourWindowStart Epoch ms the current hour window opened.
 * @property {number} hourCount       Requests made in the current hour window.
 * @property {string} dayKey          Local YYYY-MM-DD the day count belongs to.
 * @property {number} dayCount        Captures stored today.
 * @property {number|null} lastCaptureAt Epoch ms of the last request, or null.
 * @property {{ok: boolean, message: string}|null} lastResult
 */

/** @type {Readonly<CaptureState>} */
export const EMPTY_STATE = Object.freeze({
  quiet: false,
  // itemId -> epoch ms of the last NETWORK attempt (not of the last success:
  // a failed attempt must not be retried on every page view either).
  lastCaptured: {},
  hourWindowStart: 0,
  hourCount: 0,
  dayKey: "",
  // Captures STORED, acknowledged by the backend. Attempts are counted
  // separately by hourCount so the badge can never overstate what was saved.
  dayCount: 0,
  lastCaptureAt: null,
  lastResult: null,
});

const SKIP_TEXT = {
  "not-an-item-page": "Not an eBay item page.",
  quiet: "Quiet mode is on - nothing is being captured.",
  "recently-captured": "Already captured this item recently.",
  "hourly-cap": `Hourly limit of ${MAX_PER_HOUR} reached - pausing until the next hour.`,
  ok: "Capture proceeded.",
};

/**
 * eBay item id from a listing URL, or null.
 *
 * Kept identical in shape to the backend's utils.purchase_history.extract_item_id
 * so the extension cannot offer a capture for an id the API then refuses.
 */
export function extractItemId(url) {
  if (!url) return null;
  const param = /[?&]item=(\d+)/.exec(url);
  if (param) return param[1];
  const path = /\/itm\/(?:[^/?#]+\/)*(\d+)/.exec(url);
  return path ? path[1] : null;
}

/** Local calendar day as YYYY-MM-DD, for the per-day counter. */
export function localDayKey(now) {
  const d = new Date(now);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Human text for a decision reason. */
export function describeSkip(reason) {
  return SKIP_TEXT[reason] || reason;
}

/**
 * Advance the rolling windows. Returns a new state; the caller's object is
 * never mutated, so a failed write cannot leave a half-rolled state behind.
 */
export function rollWindows(state, now) {
  let out = state;
  if (!state.hourWindowStart || now - state.hourWindowStart >= HOUR_MS) {
    out = { ...out, hourWindowStart: now, hourCount: 0 };
  }
  const day = localDayKey(now);
  if (state.dayKey !== day) {
    out = { ...out, dayKey: day, dayCount: 0 };
  }
  return out;
}

/**
 * Whether to make a purchase-history request for this item, right now.
 *
 * `force` is the popup's explicit "capture this item" action. It overrides the
 * dedupe window - a user who clicks has stated an intent the window cannot
 * know about - but it does NOT override the hourly cap, which stays absolute.
 */
export function decideCapture({ itemId, now, state, force = false }) {
  if (!itemId) return { capture: false, reason: "not-an-item-page" };
  if (state.quiet) return { capture: false, reason: "quiet" };
  if ((state.hourCount || 0) >= MAX_PER_HOUR) {
    return { capture: false, reason: "hourly-cap" };
  }
  if (!force) {
    const last = (state.lastCaptured || {})[itemId];
    if (last && now - last < DEDUPE_MS) {
      return { capture: false, reason: "recently-captured" };
    }
  }
  return { capture: true, reason: "ok" };
}

/** Record that a request was about to be made. Call before the network. */
export function noteAttempt(state, { itemId, now }) {
  return {
    ...state,
    lastCaptured: { ...(state.lastCaptured || {}), [itemId]: now },
    hourCount: (state.hourCount || 0) + 1,
    lastCaptureAt: now,
  };
}

/** Record a capture the backend acknowledged as stored. */
export function noteStored(state) {
  return { ...state, dayCount: (state.dayCount || 0) + 1 };
}

/** Record the outcome text the popup shows. */
export function noteResult(state, { ok, message }) {
  return { ...state, lastResult: { ok: !!ok, message: String(message) } };
}
