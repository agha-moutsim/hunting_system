// eBay Sold History Button — background service worker (MV3, no build step).
// Flow: popup message -> item id from the active tab -> fetch eBay's
// login-required purchase-history page in the user's session -> POST the raw
// HTML to the backend -> reply {ok, body} to the popup.

function extractItemId(url) {
  if (!url) return null;
  let m = url.match(/[?&]item=(\d+)/);
  if (m) return m[1];
  m = url.match(/\/itm\/(?:[^/?#]+\/)*(\d+)/);
  return m ? m[1] : null;
}

async function captureSoldHistory() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabUrl = tab && tab.url;
  const itemId = extractItemId(tabUrl);
  if (!itemId) {
    return {
      ok: false,
      body: {
        error:
          "Not an eBay item page — open a listing (…/itm/1234567890…) first.",
      },
    };
  }

  const pageUrl = "https://www.ebay.co.uk/bin/purchaseHistory?item=" + itemId;

  let html;
  try {
    const resp = await fetch(pageUrl, {
      credentials: "include",
      headers: { accept: "text/html" },
    });
    if (!resp.ok) {
      return {
        ok: false,
        body: {
          error:
            "eBay returned HTTP " +
            resp.status +
            " — purchase history needs you to be signed in to ebay.co.uk.",
        },
      };
    }
    html = await resp.text();
  } catch (err) {
    return {
      ok: false,
      body: {
        error: "Could not fetch the purchase-history page: " + err.message,
      },
    };
  }

  const { apiBase } = await chrome.storage.sync.get({
    apiBase: "http://localhost:8000",
  });

  try {
    const resp = await fetch(
      apiBase.replace(/\/+$/, "") + "/api/extension/sold-history",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ item_id: itemId, url: tabUrl, html: html }),
      }
    );
    const body = await resp.json().catch(() => ({
      error: "Backend returned HTTP " + resp.status + " with a non-JSON body.",
    }));
    return { ok: resp.ok, status: resp.status, body: body };
  } catch (err) {
    return {
      ok: false,
      body: {
        error:
          "Backend request failed (" +
          err.message +
          ") — is the API running at " +
          apiBase +
          "?",
      },
    };
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === "capture-sold-history") {
    captureSoldHistory()
      .then(sendResponse)
      .catch((err) =>
        sendResponse({
          ok: false,
          body: { error: String((err && err.message) || err) },
        })
      );
    return true; // keep the channel open for the async response
  }
});
