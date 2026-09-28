# eBay Sold History Button (MV3)

Browser extension that captures eBay UK's **login-required** purchase-history
page for the item you are viewing and posts its raw HTML to the backend, so
the system gets **verified 7-day sales data** (CONSTRAINTS.md C4). Plain JS —
no build step.

## Why login is required

`https://www.ebay.co.uk/bin/purchaseHistory?item={id}` only renders for a
signed-in buyer. The backend cannot fetch it (and we never fabricate data —
C1), so the extension runs inside **your** logged-in eBay session and hands
the page to the API.

## Load unpacked (Chrome / Edge / Brave)

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.
4. Sign in to `ebay.co.uk`, open an item listing (`/itm/1234567890`), click
   the extension icon, then **Capture sold history**.

## Where to change the backend URL (`apiBase`)

- Default: `http://localhost:8000` (used by `background.js` and `popup.js`).
- Change it in the popup itself (field "Backend base URL") — it is saved to
  `chrome.storage.sync` under the key `apiBase`.
- To change the hard-coded default, edit `chrome.storage.sync.get({apiBase: …})`
  in `background.js` and `popup.js`.

The backend endpoint is `POST /api/extension/sold-history`
(`{item_id, url, html}`); results can be read back with
`GET /api/extension/sold-history/{item_id}`.
