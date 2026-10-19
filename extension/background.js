// eBay Sold History Button — background service worker (MV3, ES module, no build
// step).
//
// Two paths reach the same capture routine:
//   item-seen            (content script) — automatic, passive, rate-limited
//   capture-sold-history (popup)          — explicit, overrides the dedupe window
//
// All state lives in chrome.storage.local because MV3 tears the worker down
// whenever it goes idle. In-memory counters would silently reset, and a rate
// limiter that resets is not a rate limiter.
//
// The flow for one capture: item id -> fetch eBay's login-required
// purchase-history page inside the user's own session -> POST the raw HTML to
// the backend -> record what the backend said. Nothing is ever inferred here;
// if the page cannot be read, nothing is stored.

import {
  EMPTY_STATE,
  MAX_PER_HOUR,
  decideCapture,
  describeSkip,
  extractItemId,
  noteAttempt,
  noteResult,
  noteStored,
  rollWindows,
} from "./logic.js";

const DEFAULT_API_BASE = "http://localhost:8000";
const BADGE_ACTIVE = "#0d1cc4";
const BADGE_QUIET = "#4b525e";

async function loadState() {
  const { captureState } = await chrome.storage.local.get("captureState");
  return { ...EMPTY_STATE, ...(captureState || {}) };
}

async function saveState(state) {
  await chrome.storage.local.set({ captureState: state });
}

async function apiBase() {
  const { apiBase } = await chrome.storage.sync.get({
    apiBase: DEFAULT_API_BASE,
  });
  return String(apiBase || DEFAULT_API_BASE).replace(/\/+$/, "");
}

/**
 * Badge = captures the backend acknowledged as stored today, or "off" in quiet
 * mode. It deliberately does not count attempts: a badge that ticks up on
 * failures would read as data the dataset does not have.
 */
async function refreshBadge(state) {
  try {
    if (state.quiet) {
      await chrome.action.setBadgeBackgroundColor({ color: BADGE_QUIET });
      await chrome.action.setBadgeText({ text: "off" });
      return;
    }
    await chrome.action.setBadgeBackgroundColor({ color: BADGE_ACTIVE });
    await chrome.action.setBadgeText({
      text: state.dayCount ? String(state.dayCount) : "",
    });
  } catch (err) {
    // The badge is decoration. It must never break a capture.
  }
}

/** Ask the backend how much it actually holds. Never throws. */
async function fetchBackendStatus() {
  const base = await apiBase();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    const resp = await fetch(base + "/api/extension/status", {
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) {
      return { ok: false, error: "Backend returned HTTP " + resp.status };
    }
    return { ok: true, body: await resp.json() };
  } catch (err) {
    const reason = err && err.name === "AbortError" ? "timed out" : err.message;
    return { ok: false, error: "Backend unreachable (" + reason + ")" };
  }
}

/**
 * Capture one item.
 *
 * `force` is the popup's explicit action: it overrides the per-item dedupe
 * window, because a click is an intent the window cannot know about. It does
 * NOT override quiet mode or the hourly cap — those stay absolute.
 *
 * The dedupe marker is written *before* the network call, so a failed attempt
 * is not retried on every page view either; that is the whole point of the
 * window. The popup's force path is the way out of a bad marker.
 */
async function captureItem(itemId, pageUrl, { force = false } = {}) {
  const now = Date.now();
  const state = rollWindows(await loadState(), now);

  const decision = decideCapture({ itemId, now, state, force });
  if (!decision.capture) {
    // A skip is not an event: nothing is written, so browsing in quiet mode
    // does not churn storage on every page view.
    return {
      ok: false,
      skipped: decision.reason,
      body: { error: describeSkip(decision.reason) },
    };
  }

  let next = noteAttempt(state, { itemId, now });
  await saveState(next);
  await refreshBadge(next);

  const historyUrl =
    "https://www.ebay.co.uk/bin/purchaseHistory?item=" + itemId;

  let html;
  let readAt = "";
  try {
    const resp = await fetch(historyUrl, {
      credentials: "include",
      headers: { accept: "text/html" },
    });
    if (!resp.ok) {
      const message =
        "eBay returned HTTP " +
        resp.status +
        " — purchase history needs you to be signed in to ebay.co.uk.";
      next = noteResult(next, { ok: false, message: message });
      await saveState(next);
      return { ok: false, status: resp.status, body: { error: message } };
    }
    html = await resp.text();
    // When the EVIDENCE was observed, not when the upload landed. The backend
    // stamps its own clock for a payload that omits this, which is right for a
    // capture posted immediately and wrong for one that waited in a queue or
    // was retried: the stored read time would drift to whenever the request
    // finally got through, and that time is now shown next to a verified sold
    // figure. Sent as ISO-8601 with a zone; the backend normalises to UTC.
    readAt = new Date().toISOString();
  } catch (err) {
    const message = "Could not fetch the purchase-history page: " + err.message;
    next = noteResult(next, { ok: false, message: message });
    await saveState(next);
    return { ok: false, body: { error: message } };
  }

  const base = await apiBase();
  try {
    const resp = await fetch(base + "/api/extension/sold-history", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        item_id: itemId,
        url: pageUrl,
        html: html,
        captured_at: readAt,
      }),
    });
    const body = await resp.json().catch(() => ({
      error: "Backend returned HTTP " + resp.status + " with a non-JSON body.",
    }));

    if (body && body.stored === true) {
      next = noteStored(next);
    }
    next = noteResult(next, {
      ok: body && body.stored === true,
      message:
        body && body.error
          ? body.error
          : "stored=" + String(body && body.stored),
    });
    await saveState(next);
    await refreshBadge(next);
    return { ok: resp.ok, status: resp.status, body: body };
  } catch (err) {
    const message =
      "Backend request failed (" +
      err.message +
      ") — is the API running at " +
      base +
      "?";
    next = noteResult(next, { ok: false, message: message });
    await saveState(next);
    return { ok: false, body: { error: message } };
  }
}

/** The popup's manual path: capture whatever listing the active tab is on. */
async function captureActiveTab({ force = true } = {}) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabUrl = tab && tab.url;
  const itemId = extractItemId(tabUrl);
  if (!itemId) {
    return {
      ok: false,
      skipped: "not-an-item-page",
      body: {
        error:
          "Not an eBay item page — open a listing (…/itm/1234567890…) first.",
      },
    };
  }
  return captureItem(itemId, tabUrl, { force: force });
}

async function setQuiet(value) {
  let state = rollWindows(await loadState(), Date.now());
  state = { ...state, quiet: !!value };
  await saveState(state);
  await refreshBadge(state);
  return state;
}

async function statusSnapshot() {
  const state = rollWindows(await loadState(), Date.now());
  const backend = await fetchBackendStatus();
  return {
    ok: true,
    state: state,
    limits: { maxPerHour: MAX_PER_HOUR },
    apiBase: await apiBase(),
    backend: backend,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message && message.type;

  if (type === "item-seen") {
    // The content script fires for every item page view. Swallow all errors:
    // a passive path must never surface as an extension error.
    captureItem(message.itemId, message.url, { force: false })
      .then(sendResponse)
      .catch((err) =>
        sendResponse({ ok: false, body: { error: String(err) } })
      );
    return true;
  }

  if (type === "capture-sold-history") {
    captureActiveTab({ force: true })
      .then(sendResponse)
      .catch((err) =>
        sendResponse({
          ok: false,
          body: { error: String((err && err.message) || err) },
        })
      );
    return true;
  }

  if (type === "get-status") {
    statusSnapshot()
      .then(sendResponse)
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (type === "set-quiet") {
    setQuiet(message.value)
      .then(() => sendResponse({ ok: true, quiet: !!message.value }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  return false;
});

// Keep the badge honest across restarts and across midnight: the worker wakes
// on startup and on install, and both should show today's real number.
async function initBadge() {
  await refreshBadge(rollWindows(await loadState(), Date.now()));
}

chrome.runtime.onStartup.addListener(initBadge);
chrome.runtime.onInstalled.addListener(initBadge);
initBadge();
