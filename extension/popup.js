// Popup — sends the capture request to the background worker and renders
// whatever comes back: stored counts, the backend's "why not stored" reason,
// or an error message.

const statusEl = document.getElementById("status");
const buttonEl = document.getElementById("capture");
const apiBaseEl = document.getElementById("apiBase");

function show(kind, text) {
  statusEl.className = kind;
  statusEl.textContent = text;
  statusEl.style.display = "block";
}

function describe(body) {
  if (!body) return "Empty response from backend.";
  if (body.error) return body.error;
  if (body.stored === true) {
    const days30 =
      body.sold_30d === null || body.sold_30d === undefined
        ? "unknown (page did not cover 30 days)"
        : body.sold_30d;
    return (
      "Stored ✓\n" +
      "Sold (7d): " +
      body.sold_7d +
      "\n" +
      "Sold (30d): " +
      days30 +
      "\n" +
      "Captured at: " +
      (body.captured_at || "—")
    );
  }
  if (body.stored === false) {
    return "Not stored: " + (body.reason || "backend could not read the page.");
  }
  return JSON.stringify(body, null, 2);
}

chrome.storage.sync.get({ apiBase: "http://localhost:8000" }, (items) => {
  apiBaseEl.value = items.apiBase;
});

apiBaseEl.addEventListener("change", () => {
  const value =
    apiBaseEl.value.trim().replace(/\/+$/, "") || "http://localhost:8000";
  chrome.storage.sync.set({ apiBase: value });
  apiBaseEl.value = value;
});

buttonEl.addEventListener("click", () => {
  buttonEl.disabled = true;
  show("", "Capturing…");
  chrome.runtime.sendMessage({ type: "capture-sold-history" }, (response) => {
    buttonEl.disabled = false;
    if (chrome.runtime.lastError) {
      show("err", "Extension error: " + chrome.runtime.lastError.message);
      return;
    }
    if (!response) {
      show("err", "No response from the background worker.");
      return;
    }
    const text = describe(response.body);
    if (response.ok && response.body && response.body.stored === true) {
      show("ok", text);
    } else if (response.body && response.body.stored === false) {
      show("warn", text);
    } else {
      show("err", text);
    }
  });
});
