# AU UI surfaces - Phase F

Phase F finishes the AU market UI: every enabled AU surface reads the
selected marketplace, renders amounts in AUD, and states when a market is
not enabled instead of borrowing a GBP figure.

## Surfaces

- Analyze: AU band badge, AUD sourcing analysis, no UK range control, no
  History write (stated in the page), stale fee-calculator notice removed now
  that E5 is complete.
- Deep Search: AU band, AUD amounts, market switch clears stale results,
  dynamic currency in the lock notice.
- Bulk: AU band, AUD amounts, lock notice, disabled form for unready markets.
- Category Hunter: AU band, AUD amounts, lock notice, disabled scan/lookup.
- Fee Calculator: AUD, Individual default, Pro plan selector, buyer delivery
  region, GST-included note.
- Deals and Titles: served with `marketplace` and `currency` for AU.
- Hunter empty states and profit/supplier cells use the market currency.

## Acceptance

- `tests/test_au_phase_f.py` checks the public AU market and the deals,
  titles and fees routes in AUD.
- Frontend typecheck, Vitest and production build remain clean.