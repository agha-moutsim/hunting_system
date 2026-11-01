# Live AU verification checklist

Run these only when SerpApi quota is available and a signed-in eBay session exists.

1. Analyze an AU query and confirm AUD amounts and no GBP mixing.
2. Run Deep Search fast and full; confirm AUD suppliers and foreign-currency exclusions.
3. Run Bulk with multiple queries; confirm per-row currency and no cross-currency totals.
4. Category Hunter scan and lookup; confirm AU band and bench.
5. Fee calculator: Individual and Pro Starter/Basic/Featured/Anchor.
6. Deals and Titles for `EBAY_AU`.
7. Confirm History writes AU rows with `currency=AUD`.
8. Confirm extension capture upgrades 7-day demand with a signed-in UK session.