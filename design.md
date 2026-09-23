# eBay Hunter — UI Redesign Specification

> Version 1.0 · September 2026
> Status: **Awaiting your review — no code changes until you approve**
> Amends CONSTRAINTS.md §6 (design locks) — old palette retired, new palette below.

---

## 1. Goal

Redesign the Next.js frontend from a generic dark dashboard into a **recognizable, portfolio-grade product** — same features, same API, same scorecard structure — new visual identity.

- Zero logic changes. Pages, API calls, exports, Ctrl+1–8 stay exactly as they are.
- The Streamlit scorecard section order and ⚠️ Unverified labels are untouched (CONSTRAINTS C1 / §6).
- Dark theme only (unchanged).

---

## 2. Outcome

When this lands:

| You get | How you'll see it |
|--------|-------------------|
| A distinctive brand, not “another Tailwind dashboard” | Indigo + lime system, monogram logo, no emoji |
| Your 8 Noun Project icons in the nav | Converted to clean React components |
| Professional typography | Plus Jakarta Sans + JetBrains Mono for all money/percent data |
| Data you can scan fast | Tabular numbers, clearer hierarchy, stronger PASS/FAIL |
| Motion that feels intentional | Short transitions, press states, focus rings — no bounce/silliness |
| Same product behavior | `npx tsc --noEmit` clean, same 10 routes, no API contract changes |
| CONSTRAINTS.md aligned | §6 palette block updated to the new tokens |

**Definition of done:** all 9 routes build and load; palette/fonts/icons everywhere; scorecard content identical; no console errors; committed + pushed to `main`.

---

## 3. Theme

### 3.1 Color tokens (yours — source of truth)

| Token | Hex | Role |
|-------|-----|------|
| `--blue` | `#0D1CC4` | Primary brand: buttons, links, active nav, chart primary |
| `--blue-dark` | `#0B17A8` | Hover/pressed primary |
| `--lime` | `#CBFD03` | Success / PASS / profit / KPI highlights / focus accents |
| `--lime-soft` | `#BEC97D` | Muted success, secondary lime, subdued badges |
| `--dark` | `#27233F` | App shell background (replaces `#0B1120`) |
| `--white` | `#FFFFFF` | Primary text, light surfaces |
| `--gray` | `#4B525E` | Secondary surfaces, borders, muted text |

### 3.2 Derived surfaces (built FROM your tokens — not new brand colors)

| Token | Value | Use |
|-------|-------|-----|
| `bg-app` | `#27233F` | Page background |
| `bg-panel` | `#312C4D` | Cards / panels (dark lifted ~8%) |
| `bg-elevated` | `#3B3560` | Hover rows, inputs, popovers |
| `border-default` | `#4B525E` | Card/input borders (your gray) |
| `border-strong` | `#5E6575` | Focused structure, table rules |
| `text-primary` | `#FFFFFF` | Headings, primary text |
| `text-secondary` | `#B7BBC6` | Body/secondary (light gray on dark) |
| `text-dim` | `#8A90A0` | Captions, meta, disabled |
| `primary` | `#0D1CC4` | CTA, active |
| `primary-hover` | `#0B17A8` | CTA hover/active |
| `primary-on` | `#FFFFFF` | Text on primary buttons |
| `accent` | `#CBFD03` | PASS, profit, positive deltas |
| `accent-soft` | `#BEC97D` | Secondary positive, chart fill |
| `danger` | `#FF5C5C` | FAIL / errors (red must stay distinguishable on indigo) |
| `warning` | `#FFC857` | ⚠️ Unverified / pending |
| `info` | `#0D1CC4` | Links, informational chips (alias of primary) |

**Chart series (fixed order):** `#0D1CC4` → `#CBFD03` → `#BEC97D` → `#8A90A0` → `#FF5C5C` → `#FFC857`.

**Hard rules**
- Lime never used for body text on dark — accents, badges, numbers only (contrast).
- Primary blue never fills large backgrounds behind body copy.
- PASS = lime · FAIL = red · Unverified = amber + ⚠️ — always, everywhere.

### 3.3 Typography

| Role | Font | Source | Notes |
|------|------|--------|-------|
| UI / body / headings | **Plus Jakarta Sans** | Google Fonts (`next/font/google`) | Weights 400, 500, 600, 700 — modern, geometric, professional |
| Numbers, money, %, tables, code | **JetBrains Mono** | Google Fonts (`next/font/google`) | Weights 400, 500, 700 — `font-variant-numeric: tabular-nums` |

**Why this pair:** Plus Jakarta Sans reads as product-grade (not default Inter); JetBrains Mono makes £ and % columns scannable and honest — this is a numbers tool.

**Scale**

| Style | Size / line | Weight |
|-------|-------------|--------|
| Page title (h1) | 28px / 1.2 | 700 |
| Section (h2) | 20px / 1.3 | 600 |
| Card title (h3) | 16px / 1.4 | 600 |
| Body | 14px / 1.5 | 400 |
| UI label / button | 14px / 1.2 | 600 |
| Small / meta | 12px / 1.4 | 500 |
| KPI value | 28–32px mono | 700, tabular |
| Table cell numbers | 13px mono | 400–500, tabular |
| Mono code / raw JSON | 12px mono | 400 |

Letter-spacing: `+0.04em` on uppercase overlines/badges only. Never negative tracking.

### 3.4 Shape, spacing, elevation

- **Radius:** `6px` controls (buttons, inputs) · `10px` cards · `999px` pills/badges only
- **Spacing:** 4px base — use Tailwind `4/5/6/8/10/12/16` as-is (no new scale)
- **Borders:** 1px `border-default`; avoid double borders
- **Shadows:** tinted indigo — `0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(13,28,196,.08)` for elevated cards; no pure-black harsh shadows
- **Grain:** optional 2–3% noise overlay on `bg-app` only (CSS, no image asset if possible)

### 3.5 Logo / brand

- Drop the blue-purple gradient wordmark + emoji
- **Mark:** square monogram `EH` — `bg` = `#0D1CC4`, text = `#CBFD03`, radius 10px
- **Wordmark:** “eBay Hunter” in Plus Jakarta Sans 700, white; “Hunter” can carry lime accent if it stays legible
- Favicon: same monogram

### 3.6 Iconography

Use **your 8 SVGs** from `/icons`, one per nav item:

| Route | File |
|-------|------|
| `/analyze` | `noun_analyze_8392548.svg` |
| `/deep-search` | `noun_DeepDive_7968343.svg` |
| `/bulk` | `noun_bulk_7761163.svg` |
| `/hunter` | `noun_categories_8378322.svg` |
| `/tracker` | `noun_Pricing_8447584.svg` |
| `/watchlist` | `noun_wishlist_8254557.svg` |
| `/dashboard` | `noun_dashboard_8450002.svg` |
| `/history` | `noun_History_8203921.svg` |

**Conversion rules**
- One React component per icon: `frontend/components/icons/*.tsx`, `currentColor` fill, sized via `className` (default 20px)
- Strip Noun Project attribution `<text>` from rendered icons (credit lives in README “Icons” section per Noun Project license)
- Nav: inactive = `text-secondary`, hover = white, active = lime (or lime icon on primary-tinted pill)
- No emoji in nav, buttons, or status — status = colored dot/badge only

### 3.7 Components (visual only)

| Component | Spec |
|-----------|------|
| **Primary button** | `bg #0D1CC4`, white text, hover `#0B17A8`, active `scale(0.98)`, focus-visible `2px` lime ring + offset |
| **Secondary button** | transparent, `1px border-default`, white text, hover `bg-elevated` |
| **Danger button** | outline/fill `#FF5C5C`, confirm dialog unchanged |
| **Input / Select** | `bg-elevated`, border default, focus border `#0D1CC4` + lime ring; labels 12–14px |
| **Card** | `bg-panel`, radius 10, border, tinted shadow; section headers consistent |
| **Badge PASS** | lime text on `rgba(203,253,3,.12)`, pill |
| **Badge FAIL** | `#FF5C5C` on red/10%, pill |
| **Badge Unverified** | amber on amber/10%, pill, always shows ⚠️ |
| **KPI card** | label 12px uppercase dim · value mono 28px white · delta lime/red mono |
| **DataTable** | header uppercase 12px dim; numeric cols `mono` + right-align + tabular; row hover `bg-elevated` |
| **Sidebar** | `bg` slightly darker than app (`#211E35`); grouped nav; active item lime icon + lime label; brand block top; status dots bottom |
| **Topbar (mobile)** | hamburger + brand monogram; same status indicators |
| **Scorecard** | same sections/order as Streamlit; new chrome only; verdict banner: PASS lime / FAIL red / mixed amber |
| **Charts** | palette §3.2; grid `#4B525E` at 30% opacity; no default recharts blue |

### 3.8 Motion & interaction

- Transitions: **120–180ms**, `ease-out` — color, opacity, transform only
- Page/content enter: optional `opacity + 4px translateY`, stagger **≤40ms**, total ≤300ms
- Buttons: press `scale(0.98)` · Focus-visible always visible (keyboard)
- Skeletons: keep current shimmer, retint to panel/border
- `prefers-reduced-motion: reduce` → disable transforms/animation
- No parallax, no bounce, no infinite decorative loops

### 3.9 Responsive

Unchanged breakpoints (640 / 1024): desktop sidebar; <1024 hamburger + drawer; 360px no horizontal page scroll (tables scroll inside containers). Touch targets ≥40px on mobile.

---

## 4. Structure

### 4.1 System architecture (design → app)

```
design tokens (this doc)
    │
    ├─► tailwind.config.js     colors, fontFamily, radius, shadows
    ├─► app/globals.css        CSS vars, base, focus ring, reduced-motion
    ├─► app/layout.tsx         next/font (Jakarta + JetBrains), metadata, favicon
    │
    ▼
UI primitives (components/ui/*)  Button, Input, Select, Badge, Card, …
    │
    ├─► chrome     Layout (sidebar/topbar), brand monogram, icon nav
    ├─► domain     Scorecard, SupplierCard, KpiCard, DataTable, charts
    └─► pages      8 routes — visuals only, logic untouched
```

Single source of truth: **tokens in this doc → one Tailwind config → primitives → pages.** Pages never hardcode hex values.

### 4.2 Files to touch (visual only)

| File | Change |
|------|--------|
| `frontend/tailwind.config.js` | New palette, fonts, radius, shadows |
| `frontend/app/globals.css` | CSS vars, focus ring, reduced-motion, grain (opt.) |
| `frontend/app/layout.tsx` | `next/font` load, favicon, html/body classes |
| `frontend/public/favicon.ico` (or svg) | EH monogram |
| `frontend/components/icons/*.tsx` | **New** — 8 icon components from `/icons` |
| `frontend/components/Layout.tsx` | Brand, grouped nav, icons, active states |
| `frontend/components/ui/*.tsx` | Button, Input, Select, Textarea, Badge, Card, ConfirmDialog, Spinner, Skeleton, EmptyState, KpiCard, StatusDots |
| `frontend/components/Scorecard.tsx` | Surfaces + verdict colors |
| `frontend/components/SupplierCard.tsx` | Card/badge tokens |
| `frontend/components/DataTable.tsx` | Mono numerics, header, hover |
| `frontend/components/charts/index.tsx` | New series colors |
| `frontend/app/*/page.tsx` (8) | Class swaps only if primitives don’t cover it |
| `README.md` | Noun Project icon credit |
| `CONSTRAINTS.md` §6 | Palette line → new tokens |

**Do not touch:** `backend/**`, `lib/api.ts` contracts, `lib/types.ts` shape, export logic, Ctrl+1–8 behavior, scorecard section order.

### 4.3 Page inventory (unchanged IA)

| # | Route | Ctrl | Purpose |
|---|-------|------|---------|
| 1 | `/analyze` | 1 | Single product + scorecard |
| 2 | `/deep-search` | 2 | Research + suppliers + sold data |
| 3 | `/bulk` | 3 | Batch + export |
| 4 | `/hunter` | 4 | Category scan → lookup |
| 5 | `/tracker` | 5 | Price tracker + alerts |
| 6 | `/watchlist` | 6 | Watchlist + saved searches |
| 7 | `/dashboard` | 7 | KPIs + charts + log sale |
| 8 | `/history` | 8 | Past analyses |

`/` → redirect `/analyze`.

---

## 5. Implementation plan

| Phase | Work | Files | Est. |
|-------|------|-------|------|
| **R1** | Tokens: tailwind + globals + fonts + layout + favicon | 5 | Small |
| **R2** | Brand + icons: monogram, 8 components, Layout nav | 10 | Medium |
| **R3** | Primitives: Button, Input, Select, Badge, Card, Confirm, Spinner, Skeleton, EmptyState, KpiCard, StatusDots | 12 | Medium |
| **R4** | Domain: Scorecard, SupplierCard, DataTable, charts | 4 | Medium |
| **R5** | Pages: class audit ×8, mobile check, focus/reduced-motion | 8 | Small |
| **R6** | CONSTRAINTS.md §6 + README icon credit; verify build; commit + push | 3 | Small |

**Order:** R1 → R2 → R3 → R4 → R5 → R6. Stop after R2 for a mid-point visual check if you want.

**Verification each phase:** `npx tsc --noEmit` · `npm run build` · spot-check routes in browser · commit + push.

**Risk / scope guard:** pure presentation; revert = `git revert` on the redesign commits. No API, DB, or pipeline risk.

---

## 6. Out of scope (v1 redesign)

- Light mode / theme toggle
- New pages or navigation items
- Auth, payments, websockets (still CONSTRAINTS non-goals)
- Backend, scrapers, scorecard content rules
- Replacing your icons with an icon library
- Animations libraries (CSS/Tailwind only)

---

## 7. Approval

- [ ] **Palette** (§3.1 + derived surfaces §3.2)
- [ ] **Fonts** — Plus Jakarta Sans + JetBrains Mono
- [ ] **Icons** — your 8, attribution moved to README
- [ ] **Structure & architecture** (§4)
- [ ] **Plan R1–R6** (§5)
- [ ] CONSTRAINTS.md §6 amendment accepted

**Approved by:** _________________  **Date:** _________

**Next after approval:** start **R1** (tokens + fonts), commit, push, then R2.
