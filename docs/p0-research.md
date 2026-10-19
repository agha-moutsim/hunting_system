# P0 Research — eBay purchase history, VeRO list, official UK fee schedule

> Date: **29 September 2026** · Status: **Research only — no repo code/config changed**
> Scope: Q1 purchase-history feasibility, Q2 VeRO official list, Q3 fee-model delta.
> All test scripts were throwaway and live in `C:\Users\AGHAMO~1\AppData\Local\Temp\opencode\`.

## 0. Stack under test (what "the repo's scraper" means)

- `backend/scrapers/ebay.py` — eBay Browse API (OAuth client-credentials) primary, `requests` + `SCRAPE_CONFIG` headers fallback. Source: repo file.
- `backend/scrapers/ebay_sold.py` — `requests.Session()` with `SCRAPE_CONFIG` UA/Accept headers against `/sch/i.html?LH_Complete=1&LH_Sold=1`. Source: repo file.
- `backend/scrapers/base.py` — `BaseScraper`: Playwright Chromium headless + `playwright-stealth`, same `SCRAPE_CONFIG` UA, `domcontentloaded` + 3 s settle. Source: repo file. This is the mechanism reused below as "Playwright path".
- Test item IDs came from the repo's own search path: `EbayScraper.search("wireless earbuds")` → Browse API → `406803296693`, `198655065698`, `237083359281` (empirical: `q1_step1_items.py`).

---

## Q1 — Purchase history (7-day sold rows) feasibility

### (a) Exact URL pattern — `/itm/{id}/pnh` is NOT it

- The ZIK extension's own CRX (Chrome Web Store id `lhdknendolkhkmfpklppgpbimpbnlgel`, v2.9, downloaded from `https://clients2.google.com/service/update2/crx?response=redirect&...&x=id%3Dlhdknendolkhkmfpklppgpbimpbnlgel%26uc`) contains, in `manifest.json`, content-script matches for `https://*.ebay.co.uk/bin/purchaseHistory*`, `https://*.ebay.co.uk/itm/*` and `https://*.ebay.com/itm/purchaseHistory*`. Source: CRX `manifest.json`.
- The button builds the URL as `new URL("/bin/purchaseHistory", origin)` + `?item={itemId}` (+ `zik_open_ui=1`): code string `function KU(e,t=!0){const n=new URL("/bin/purchaseHistory",Of());return n.searchParams.set("item",String(e)),...}`. Source: CRX `content-scripts/main.js` (same builder in `content-scripts/product-page.js`).
- **Real pattern: `https://www.ebay.co.uk/bin/purchaseHistory?item={itemId}`** (alternative `https://www.ebay.com/itm/purchaseHistory?item={itemId}` also matched by the manifest).
- `/itm/{id}/pnh` is a red herring: it never appears in the extension source, and eBay answers it with a bot wall (below).
- Chrome Web Store listing describes the button as opening "purchase history" with "price, date, and quantity sold". Source: https://chromewebstore.google.com/detail/ebay-sold-history-button/lhdknendolkhkmfpklppgpbimpbnlgel

### (b) Empirical fetches (3 item IDs, both repo mechanisms)

**Path 1 — `requests` + `SCRAPE_CONFIG` headers (repo's ebay_sold mechanism)** (empirical: `q1_step2_requests.py`, `q1_step6_bin.py`):

| URL                                                   | Status                                                                | Final page                                                                                   | Sold rows               |
| ----------------------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------- |
| `/bin/purchaseHistory?item=406803296693`              | 200                                                                   | `splashui/challenge?...ru=.../bin/purchaseHistory...` — "Pardon our interruption…" (13.7 KB) | 0 date hits             |
| `/bin/purchaseHistory?item=198655065698`              | 200                                                                   | same challenge redirect                                                                      | 0                       |
| `/bin/purchaseHistory?item=237083359281`              | 200                                                                   | same challenge redirect                                                                      | 0                       |
| `/itm/{id}/pnh` (all 3, earlier run)                  | 403 "Error Page \| eBay" (1.8 KB), later 400 "Discover error \| eBay" | —                                                                                            | 0                       |
| `/itm/purchaseHistory?item={id}`                      | 200 → challenge                                                       | —                                                                                            | 0                       |
| `/itm/{id}` plain item page (first calls)             | 200, 1.0 MB                                                           | item page renders                                                                            | no per-transaction rows |
| `/itm/{id}` plain item page (later call)              | 403 "Error Page \| eBay"                                              | —                                                                                            | —                       |
| Sold search `/sch/i.html?...&LH_Complete=1&LH_Sold=1` | **403** "Error Page \| eBay", `li.s-item` = 0                         | —                                                                                            | —                       |

**Path 2 — Playwright + stealth (`BaseScraper` mechanism, warm-up on the item page first)** (empirical: `q1_step4_playwright.py`, `q1_step8_pw_bin.py`, `q1_step9_longwait.py`):

- `/itm/{id}/pnh` → 403 "Error Page | eBay" (item 406803296693) or HTTP 400 "Discover error | eBay" (other two). 0 date rows.
- `/bin/purchaseHistory?item={id}` → HTTP 200 but **final URL `https://www.ebay.co.uk/splashui/captcha?...ru=https%3A%2F%2Fsignin.ebay.co.uk%2Fws%2FeBayISAPI.dll%3FSignIn...ru%3D...%252Fbin%252FpurchaseHistory%253Fitem%253D{id}...`**, title "Security measure | eBay" — i.e. the chain demands **Sign-in** before returning to the purchase-history URL. `date_hits=0`, `sold` keyword = 0.
- Waiting 30 s on that captcha (6 polls × 5 s) never cleared: URL stayed on `splashui/captcha`, title "Security measure | eBay" (empirical: `q1_step9_longwait.py`).
- Plain item page via Playwright: 200, 2.5 MB, title = the listing title; contains cumulative counters only — `8 sold today`, `20 sold`, plus `1172 sold` / `1734 sold` inside "also-bought" recommendation cards. No date/price/quantity transaction rows anywhere (empirical: grep over `pw_plain_198655065698.html`).

**The extension itself only parses rows after eBay rendered the page in a signed-in browser**: CRX `content-scripts/purchase-history.js` logs `[PurchaseHistory] Parsing purchase history page` → `{purchases: [...]}`, and it runs only on `*/bin/purchaseHistory*` / `*/itm/purchaseHistory*` matches.

### (c) Verdict

**LOGIN-REQUIRED (with bot wall on top).** Not feasible server-side with either repo mechanism as shipped.

Evidence:

1. Redirect chain for `/bin/purchaseHistory?item={id}` targets `signin.ebay.co.uk/ws/eBayISAPI.dll?SignIn` with the purchase-history URL as the return target (Playwright, final URL captured above) — that is eBay explicitly gating the resource behind authentication, not just UA sniffing.
2. Unauthenticated responses contain **zero** sold rows (0 date hits in every one of ~15 requests/page loads across both mechanisms).
3. Even after the sign-in gate there is a `splashui/challenge` / `splashui/captcha` bot wall that `requests` (403/challenge) and headless Playwright (stuck 30 s) do not clear.
4. The JS-only reading ("Playwright will render it") is disproved: the rendered Playwright response was the captcha page, not the table.

What _is_ reachable server-side: the item page intermittently renders via Playwright with aggregate counters (`N sold today`, `N sold`) — usable as a weak demand signal, not as 7-day sold rows.

---

## Q2 — eBay VeRO official list source

### (a) Verified official URLs (each fetched; status noted)

| URL                                                                                                                 | Result                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `https://www.ebay.co.uk/sellercentre/protection/verified-rights-owner-profiles`                                     | **200** — UK "Verified Rights Owner (VeRO) profiles" directory with A–Z participant list (empirical: Playwright fetch, `q2q3_fetch.py`)                                                                                                          |
| `https://www.ebay.com/vero`                                                                                         | 200 → redirects to `https://pages.ebay.com/vero/` — VeRO programme explainer (empirical: same fetch)                                                                                                                                             |
| `https://www.ebay.co.uk/help/policies/listing-policies/selling-policies/intellectual-property-vero-program?id=4349` | fetched → **captcha** "Please verify yourself to continue" (webfetch) / `splashui/captcha` (Playwright). Content (VeRO participant-profiles tab, NOCI via `vero@ebay.com`) seen in search-result excerpt only — needs a re-fetch, see Open items |
| `https://www.ebay.co.uk/vero/notice`                                                                                | **404** (webfetch)                                                                                                                                                                                                                               |
| `https://www.ebay.com/vero/notice`                                                                                  | **404** (webfetch)                                                                                                                                                                                                                               |
| `https://pages.ebay.com/vero/participants.html`, `https://pages.ebay.co.uk/vero/participants.html`                  | **404** (webfetch)                                                                                                                                                                                                                               |
| `https://pages.ebay.de/vero/participants.html`                                                                      | **200** — static HTML participant directory exists on the German site only (webfetch)                                                                                                                                                            |
| `https://vero.corp.ebay.com/s`                                                                                      | VeRO Portal — Register/Login + reCAPTCHA (search result / fetch)                                                                                                                                                                                 |

**Best UK URL: `https://www.ebay.co.uk/sellercentre/protection/verified-rights-owner-profiles`.**

### (b) Machine-readable? — HTML only

- Empirical scan of the fetched UK page: **no** JSON-LD, **no** `.csv`/`.json`/`.xls`/`download` links, **no** API hints. It is a single A–Z HTML page whose participant names are anchors to PDF profiles on `https://ir.ebaystatic.com/pictures/aw/pics/pdf/us/help/community/vpp/*.pdf` (empirical: `q2_count_and_sold_test.py`).
- **Participant count: 1,140 profile anchors / 1,135 unique names** after excluding the A–Z index letters and nav links (empirical: anchors between the `VeRO participant profiles` heading and the next heading, `q2_count_and_sold_test.py`).
- eBay's own caveats printed on that page: "The content is provided and managed by the rights owners themselves", **"This isn't a complete list of all brands with IP rights on eBay"**, **"Not all rights owners in the VeRO programme have a participant profile listed here."** Source: `https://www.ebay.co.uk/sellercentre/protection/verified-rights-owner-profiles`.
- The programme contact/listing flow is email-based (`vero@ebay.com`), no downloadable register: Source: `https://www.ebay.com/vero`.

### (c) Recommendation for `backend/data/vero_brands.json`

- **Page parse, monthly cadence.** There is no official download/API to sync, so: Playwright-fetch the UK directory (the repo's `BaseScraper.fetch` already returns 200 on it), extract anchor text → write `{"fetched_at": ..., "source_url": ..., "names": [...]}`.
- Monthly is enough: participant lists drift slowly, and the page carries no "last updated" stamp; keep a manual merge-list beside it for brands you know are enforcing but are absent (the page admits it is incomplete — treat it as an advisory filter, never as a guarantee of safety).
- `backend/data/` currently holds no `vero_brands.json` and nothing in the codebase references VeRO (empirical: `Get-ChildItem backend/data` + grep `vero|VeRO` across `*.py` → no hits), so this is a greenfield file.
- Do **not** hit the page on every analysis run — one Playwright page-load per refresh, cached to disk.

---

## Q3 — eBay UK official fee schedule vs the decided model

**Decision (implemented):** 13.5% final value + 0.03% listing + 20% VAT on fees + 3% returns buffer.
_(Update: `PROFIT_CONFIG` was 12.8% when this was observed; it now carries the decided model — 13.5 / 0.03 / VAT 20 / returns 3 — per CONSTRAINTS.md C3.)_
_**Update 2026-10-20 - shipped and verified live.** The default is now the transcribed published card (`uk-rate-card-2026-09-30`, archived sources cited in `backend/engine/fees.py`); the 13.5% + 0.03% model stays selectable as `v1-static`. Verified against the running stack the same day: business sale GBP 24.99, Everything Else (the engine's stated default), 2% promoted, GBP 3.20 postage paid, GBP 9.40 supplier -> FVF GBP 3.22 + per-order GBP 0.40 + regulatory GBP 0.09 + promoted GBP 0.50 + VAT GBP 0.84 = GBP 5.05 cost, net GBP 19.94, profit GBP 6.59, margin 26.4%; reverse target 30% solves GBP 26.86 (engine check recomputes 30.0 / GBP 8.06; forward at 26.86 returns 30.0); break-even (0% target, same costs) solves GBP 16.63 with a recomputed profit of GBP 0.01 at that price - the solve rounds up to the penny, so break-even is stated as the lowest price that does not lose money, not as a zero-profit price. Q3's remaining gap: performance modifiers (+6pp / +4pp / Top-rated -10%) and Shop listing allowances are still not modelled; the listing cost is a per-sale input, not a per-listing charge (v1-static keeps its 0.03% line)._

### Official facts (primary sources, all fetched 29 Sep 2026)

1. **Final value fee — business sellers:** variable % of the _total amount of the sale_ (item price + postage + applicable taxes) **plus a per-order fee**. Source: `https://www.ebay.co.uk/help/selling/fees-credits-invoices/fees-business-sellers?id=4809` (page states "Last updated on 4 August, 2026").
2. **Per-order fixed fee:** "For orders £10.00 or less the per-order fee is **£0.30**, for orders over £10.00 the per-order fee is **£0.40**." Same URL as (1). The 12 Feb 2026 change is confirmed on the rate card: Up to £10 £0.30 → £0.30 (unchanged); Above £10 £0.30 → **£0.40**. Source: `https://www.ebay.co.uk/sellercentre/news/2026-january/rate-card-change`.
3. **FVF range by category:** 55 category rows, base rates **5% (NFT categories: Art NFTs, Emerging NFTs, Film/Music/Sport/CCG NFTs) to 12.9%** (Women's Bags & Handbags, Crafts, Event Tickets, E-cigarette parts, Watches parts, Pet Supplies, Wholesale & Job Lots, Everything Else), with tiered maxima — highest is **Jewellery & Watches 14.9% up to £1,000 then 4% above**. Common rates: 9.9%, 10.9%, 11.9%, 12.5% (Business/Office & Industrial from 12 Feb 2026), 12.9%. Source: category table, `fees-business-sellers?id=4809` (empirical: parsed table → `fvf_table.json`).
4. **Modifiers:** Below Standard sellers pay **+6 percentage points** (+7 after 4 consecutive months); "Very high" INR rate adds **+4 pp** (5 pp after 4 consecutive months); Top-rated sellers get a **10% discount on the variable portion** (not the per-order fee). Source: `fees-business-sellers?id=4809`.
5. **Insertion / listing fee:** "When you list an item for sale on eBay, we charge a fee per listing… depends on whether or not you have a Shop subscription". Business rate card: **No Shop → 30p per additional fixed-price listing**; Basic £27/mo (250 free fixed-price), Featured £77/mo (1,500), Anchor £437/mo (unlimited); listing fees also recur monthly for Good 'Til Cancelled listings and on relist. Source: `fees-business-sellers?id=4809`. (Private-seller equivalent: 300 free listings/mo then **35p** each — `https://www.ebay.co.uk/help/selling/fees-credits-invoices/fees-private-sellers?id=4822`.)
6. **Regulatory operating fee:** "we charge a regulatory operating fee of **0.35%**, calculated on the total amount of the sale (item price, postage, any applicable taxes)". Source: `fees-business-sellers?id=4809`. It is **subject to VAT** — Seller Centre works the example: 0.35% + 0.07% VAT = **0.42%**; no cap. Source: `https://www.ebay.co.uk/sellercentre/selling/start-selling/fees`.
7. **VAT on fees:** every fee page states **"All fees displayed on this page are exclusive of VAT"** (`fees-business-sellers?id=4809`; rate-card page), and eBay's tax policy says "Depending on where you live Value Added Tax (VAT)… might apply to your eBay fees… eBay will add the tax as a separate charge on your seller invoice or include the tax in our fees." Source: `https://www.ebay.co.uk/help/policies/selling-policies/tax-policy?id=4348`. UK standard rate 20%. So: **fees are quoted ex-VAT, 20% VAT is added.**

### Delta table — user model vs official (business seller, UK, no Shop subscription)

| Component                                     | Official (29 Sep 2026)                                                                                                            | User model                                                              | Delta                                                                                                                     |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Final value fee                               | Category-variable **5%–14.9%** of _total incl. postage_ (typical 10.9%; 12.9% common for generic/Everything-Else-type categories) | Flat **13.5%**                                                          | +2.6 pp vs 10.9% typical; **−1.4 pp** vs 12.9%; +0.6 pp above the highest tier start. Flat rate hides the category spread |
| Per-order fee                                 | **£0.30** (≤£10) / **£0.40** (>£10) per order                                                                                     | **absent**                                                              | Under-costs every order: adds **+6.0 pp** of the sale at £5, **+3.0 pp** at £10, **+2.0 pp** at £20, **+1.1 pp** at £35   |
| Listing / insertion fee                       | **30p per additional fixed-price listing** (no shop) or subscription allowances; recurs monthly on GTC                            | **"0.03%"** (≈ £0.006 on a £20 sale)                                    | Model effectively ignores listing cost — real cost is a flat 30p/listing, i.e. orders of magnitude larger                 |
| Regulatory operating fee                      | **0.35%** of total sale → **0.42%** incl. VAT                                                                                     | **absent**                                                              | −0.42 pp                                                                                                                  |
| VAT                                           | Fees quoted **ex-VAT**, 20% added (tax policy)                                                                                    | **20% VAT applied to fees**                                             | **Aligned**                                                                                                               |
| Returns buffer                                | no official counterpart (eBay charges no blanket returns fee; refunds/credits are per-case)                                       | **3%**                                                                  | User-only risk buffer — fine to keep, label as buffer not eBay fee                                                        |
| Performance modifiers                         | +6 pp Below Standard, +4/5 pp Very High INR, −10% TRS on variable portion                                                         | not modelled                                                            | Unmodelled upside/downside                                                                                                |
| **Worked example (10.9% category, £20 sale)** | 2.18 + 0.40 + 0.07 = £2.65 → ×1.20 = **£3.18 = 15.9%**                                                                            | 2.70 + 0.006 = £2.71 → ×1.20 = **£3.25 = 16.24%** (+3% buffer = 19.24%) | **+£0.07 over official** at £20 — model is well calibrated mid-band                                                       |
| **Worked example (£5 sale, ≤£10 order)**      | 0.545 + 0.30 + 0.018 = £0.86 → ×1.20 = **£1.04 = 20.7%**                                                                          | **£0.81 = 16.24%** (+buffer 19.24%)                                     | **Under-costs by ~4.5 pp** — the flat model misses the per-order fee where it dominates                                   |
| **Worked example (£35 sale)**                 | 3.815 + 0.40 + 0.123 = £4.34 → ×1.20 = **£5.21 = 14.9%**                                                                          | **£5.68 = 16.24%** (+buffer 19.24%)                                     | **Over-costs by ~1.4 pp** before buffer                                                                                   |

_(Worked examples are arithmetic on the official rates above — empirical: calculation script output, reproducible from the quoted fee page.)_

**Summary one-liner:** the decided 13.5 % + 0.03 % + 20 % VAT model lands within ±0.1 pp of a real 10.9 %-category £20 order (16.2 % vs 15.9 %), but it **omits the £0.30/£0.40 per-order fee, the 0.35 %+VAT regulatory operating fee and the flat 30p listing fee**, so it **under-prices small orders (~£5–10) by ~4–5 pp** and **over-prices large orders (~£35) by ~1.4 pp**; the 3 % returns buffer is a user-side risk margin, not an eBay charge.

---

## Open items

1. **Authenticated purchase-history test** — nobody has yet loaded `/bin/purchaseHistory?item={id}` with a signed-in eBay session; if that returns the table, the whole Q1 path becomes a cookie-carrying Playwright job. Needs the owner's login (out of scope for this unauthenticated research).
2. **Re-fetch the VeRO help article** `.../intellectual-property-vero-program?id=4349` — both our fetch paths hit the captcha; the URL is correct but its content is currently confirmed only from a search-result excerpt.
3. **UK VeRO page completeness** — verify whether the 1,135-name list changes materially month-to-month (no `Last updated` stamp) before fixing a refresh cadence; also decide whether `pages.ebay.de/vero/participants.html` (static, but German site) is worth cross-checking.
4. **Item-page counters as a demand proxy** — `N sold today` / cumulative `N sold` are visible in Playwright-rendered item pages; validate whether they are eBay-authoritative and whether they can approximate a 7-day signal. Not confirmed as reliable.
5. **Sold search (`LH_Sold=1`) is 403 via `requests`** (reproduced today) — the repo's `ebay_sold.py` scrape fallback is currently dead for the same bot wall; only the Browse API path works. Worth confirming against production behaviour before relying on `total_sold_7d`.
6. **Category-specific FVF** — the delta table uses 10.9 %/12.9 % as reference points; the fee-calculator API (shipped 2026-10-20; it replaces the static model as the default - see the update under "Decision (implemented)" above - and prices from archived transcriptions rather than a live pull, because the live page is bot-walled) must pull the live table from `fees-business-sellers?id=4809` and add the performance modifiers (+6 pp / +4 pp / TRS −10 %).
7. **Bot-wall variance** — the same URL returned 403, 400 and 200-with-challenge within one session; any future automated fetch of VeRO/fee pages must tolerate this (retry + treat challenge page as failure, never parse it).
