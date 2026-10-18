// Content script - eBay item pages only.
//
// Its whole job is to say "this item is on screen" and let the background
// worker decide what to do. All rate limiting, dedupe and network work lives in
// background.js/logic.js, so this file holds no policy that could drift from
// the tested one.
//
// Self-contained on purpose: content scripts are classic scripts and cannot use
// ES module imports, so the id pattern below is duplicated from logic.js and
// pinned by the tests in frontend/lib/extensionLogic.test.ts.

(() => {
  const ITEM_PATTERNS = [/[?&]item=(\d+)/, /\/itm\/(?:[^/?#]+\/)*(\d+)/];

  function extractItemId(url) {
    if (!url) return null;
    for (const re of ITEM_PATTERNS) {
      const m = re.exec(url);
      if (m) return m[1];
    }
    return null;
  }

  function report() {
    const itemId = extractItemId(window.location.href);
    if (!itemId) return;
    try {
      // Reading lastError is what stops "Unchecked runtime.lastError" noise
      // when the service worker is asleep or the extension was just reloaded.
      chrome.runtime.sendMessage(
        { type: "item-seen", itemId, url: window.location.href },
        () => void chrome.runtime.lastError
      );
    } catch (err) {
      // Extension context invalidated (reloaded mid-page). Nothing to do.
    }
  }

  report();

  // eBay navigates between listings without a full page load in some flows, so
  // a single report at document_idle is not enough. popstate covers back and
  // forward; the item id is only re-reported when it actually changes, which
  // keeps the background worker's dedupe window as the real gate.
  let lastReported = extractItemId(window.location.href);
  window.addEventListener("popstate", () => {
    const current = extractItemId(window.location.href);
    if (current && current !== lastReported) {
      lastReported = current;
      report();
    }
  });
})();
