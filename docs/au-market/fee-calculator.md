# AU Fee Calculator - Phase E5

Phase E5 enables the standalone fee calculator for `EBAY_AU` in AUD.

## The flip

`config.MARKETPLACES["EBAY_AU"]["fee_calculator_ready"]` is now `True`, so:

- the public marketplace record exposes `fee_table: "au-rate-card-2026-10-09"`;
- `fee_warning` is `None`;
- `GET /api/fees/table` and `POST /api/fees/calculate` return 200 for AU.

Markets without a card (US, DE, CA) remain refused with their no-card sentence.

## API additions

`/api/fees/table` now also returns:

- `currency_symbol`
- `default_seller_type` (`private` for AU)
- `default_plan` (`starter` for AU)
- `plans` (Pro Starter/Basic/Featured/Anchor with monthly and per-order fees)
- `tax` (`GST`, 10%, included)
- `domestic_region` (`au`)
- `buyer_regions`

`/api/fees/calculate` now also returns `marketplace`, `currency` and
`currency_symbol`.

## UI

`frontend/app/fees/page.tsx` now:

- reads the marketplace and formats every amount with `formatMoney`;
- defaults to the Individual branch using `market_defaults`;
- shows an eBay plan selector for a business sale, with per-plan rates;
- offers domestic Australia vs outside Australia for the international fee;
- hides the category selector for Individual AU selling;
- shows the GST-included note instead of the VAT checkbox for AU.

`FeeBreakdown` formats in the table's own currency and shows `vat_note`.

## Pins

- `tests/test_au_fee_calculator.py` - AU calculator enabled and labelled AUD,
  published totals, selected plan, international fee, US refusal.
- `tests/test_markets.py`, `tests/test_au_market_config.py`,
  `tests/test_au_analyze.py` - updated to the enabled state.
- `frontend/lib/fees.test.ts` - market defaults and AU controls.