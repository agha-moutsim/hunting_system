// Popup — renders the extension's real state, never a placeholder.
//
// Two different numbers live here and they are deliberately kept apart:
//   "Stored today"      — captures this extension made that the backend
//                         acknowledged as saved.
//   "Items captured"    — the backend's own row count, so the popup cannot
//                         overstate the dataset even if a POST went missing.
// The last outcome line shows whatever the backend said, verbatim.

const dayCountEl = document.getElementById("dayCount");
const hourCountEl = document.getElementById("hourCount");
const backendCountEl = document.getElementById("backendCount");
const lastAtEl = document.getElementById("lastAt");
const statusEl = document.getElementById("status");
const captureEl = document.getElementById("capture");
const quietEl = document.getElementById("quiet");
const apiBaseEl = document.getElementById("apiBase");

let quiet = false;

function show(kind, text) {
  statusEl.className = kind || "";
  statusEl.textContent = text;
  statusEl.style.display = "block";
}

function hide() {
  statusEl.style.display = "none";
}

function formatTime(ms) {
  if (!ms) return "—";
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response);
    });
  });
}

function render(payload) {
  if (!payload || !payload.ok) {
    show(
      "err",
      "Extension error: " +
        ((payload && payload.error) ||
          "no response from the background worker.")
    );
    captureEl.disabled = true;
    return;
  }

  const state = payload.state || {};
  quiet = !!state.quiet;
  quietEl.checked = quiet;
  captureEl.disabled = quiet;

  dayCountEl.textContent = state.dayCount || 0;
  hourCountEl.textContent =
    (state.hourCount || 0) +
    " / " +
    (payload.limits && payload.limits.maxPerHour);
  lastAtEl.textContent = formatTime(state.lastCaptureAt);

  const backend = payload.backend || {};
  if (backend.ok && backend.body) {
    backendCountEl.textContent = backend.body.items_captured;
    backendCountEl.title =
      "Last 24h: " + backend.body.items_captured_24h + " captured";
  } else {
    backendCountEl.textContent = "—";
  }

  // Priority: a refusal the user should know about, then the last outcome,
  // then silence. Quiet mode is stated plainly because it silently stops work.
  if (quiet) {
    show("warn", "Quiet mode is on — nothing is being captured.");
    return;
  }
  if (!backend.ok) {
    show("warn", (backend.error || "Backend unreachable") + ".");
    return;
  }
  const last = state.lastResult;
  if (last && last.message) {
    show(last.ok ? "ok" : "warn", last.message);
    return;
  }
  hide();
}

async function refresh() {
  render(await send({ type: "get-status" }));
}

chrome.storage.sync.get({ apiBase: "http://localhost:8000" }, (items) => {
  apiBaseEl.value = items.apiBase;
});

apiBaseEl.addEventListener("change", () => {
  const value =
    apiBaseEl.value.trim().replace(/\/+$/, "") || "http://localhost:8000";
  chrome.storage.sync.set({ apiBase: value }, () => {
    apiBaseEl.value = value;
    refresh();
  });
});

quietEl.addEventListener("change", async () => {
  const result = await send({ type: "set-quiet", value: quietEl.checked });
  if (!result || !result.ok) {
    show(
      "err",
      "Could not change quiet mode: " +
        ((result && result.error) || "unknown error")
    );
    quietEl.checked = !quietEl.checked;
    return;
  }
  refresh();
});

captureEl.addEventListener("click", async () => {
  captureEl.disabled = true;
  show("", "Requesting the purchase-history page…");
  const response = await send({ type: "capture-sold-history" });

  if (!response) {
    show("err", "No response from the background worker.");
  } else if (response.skipped) {
    show("warn", (response.body && response.body.error) || "Skipped.");
  } else if (response.body && response.body.error) {
    show("err", response.body.error);
  } else if (response.body && response.body.stored === true) {
    const days30 =
      response.body.sold_30d === null || response.body.sold_30d === undefined
        ? "unknown (page did not cover 30 days)"
        : response.body.sold_30d;
    show(
      "ok",
      "Stored\n" +
        "Sold (7d): " +
        response.body.sold_7d +
        "\n" +
        "Sold (30d): " +
        days30 +
        "\n" +
        "Captured at: " +
        (response.body.captured_at || "—")
    );
  } else if (response.body && response.body.stored === false) {
    show(
      "warn",
      "Not stored: " +
        (response.body.reason || "backend could not read the page.")
    );
  } else {
    show("err", JSON.stringify(response.body || response, null, 2));
  }

  refresh();
});

refresh();
