# eBay Sold History Button (MV3)

Browser extension that captures eBay UK's **login-required** purchase-history
page while you browse listings, and posts its raw HTML to the backend, so the
system gets **verified 7-day sales data** (CONSTRAINTS.md C4). Plain JS — no
build step.

## Two ways a capture happens

| Path    | Trigger                                | Limited by                 |
| ------- | -------------------------------------- | -------------------------- |
| Passive | You open a listing (`/itm/…`)          | dedupe window + hourly cap |
| Manual  | **Capture this item now** in the popup | the same hourly cap only   |

Passive capture is the point of this version: the three-click ritual was the
reason the dataset held a single row.

## What it will not do

- It never navigates or crawls. It reads the purchase-history page for a
  listing you already opened, nothing else. Automating an account's own
  navigation is how accounts get restricted, and a restricted account loses the
  data source.
- It never guesses. If the page cannot be read, the backend stores nothing and
  says why.
- It never runs unattended. **Quiet mode** stops everything, automatic and
  manual alike, and the badge reads `off`.

## Safety limits, and why they are tested

`logic.js` holds both rules as pure functions and
`frontend/lib/extensionLogic.test.ts` covers them: a rate limiter nobody tests
is a rate limiter that has quietly stopped working.

- `DEDUPE_MS` — one request per item per 6 hours.
- `MAX_PER_HOUR` — 60 requests an hour, counted as _attempts_, so a page that
  fails to parse is not retried on every later view either.
- A failed attempt still writes the dedupe marker, because the request was
  still made. The popup's manual button is the deliberate way past it; only the
  hourly cap is absolute.

## What the popup shows

- **Stored today** — captures this extension made that the backend saved.
- **Requests this hour** — attempts, against the cap.
- **Items captured** — the backend's own row count from
  `GET /api/extension/status`, so the popup cannot overstate the dataset.
- **Last request** — when, and the backend's own words about how it went.

An attempt is not a row: the badge and "stored today" move only when the
backend answers `stored: true`.

## Load unpacked (Chrome / Edge / Brave)

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.
4. Sign in to `ebay.co.uk` and browse listings. Reload the extension on the
   extensions page (`↻`) to pick up this version. The content script stays
   scoped to `/itm/*`; the manifest also grants access to the local API on
   `localhost:8000` / `127.0.0.1:8000` so the popup and capture POST can reach
   the backend.

## Where to change the backend URL (`apiBase`)

- Default: `http://localhost:8000`, read by `background.js` and editable in the
  popup footer.
- Saved to `chrome.storage.sync` under the key `apiBase`.

## Files

| File                      | Role                                            |
| ------------------------- | ----------------------------------------------- |
| `manifest.json`           | MV3 manifest; content script scoped to `/itm/*` |
| `logic.js`                | Pure decision logic — no `chrome.*`, no network |
| `content.js`              | Reports the listing on screen; holds no policy  |
| `background.js`           | Owns state, rate limits and every network call  |
| `popup.html` / `popup.js` | Status, quiet toggle, manual capture            |

## API

- `POST /api/extension/sold-history` — `{item_id, url, html}`; answers
  `{stored, sold_7d, sold_30d, captured_at}` or `{stored: false, reason}`.
- `GET /api/extension/sold-history/{item_id}` — latest capture, or 404.
- `GET /api/extension/status` — stored row counts for the popup. Read-only;
  it fetches nothing.
