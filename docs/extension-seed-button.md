# Extension seed button

The popup can seed a bounded list of eBay item ids without navigating or
crawling.

Rules:

- Maximum 25 item ids per seed run.
- One capture per item, forced past the per-item dedupe window.
- The hourly cap remains absolute.
- Quiet mode refuses to seed.
- Captures are spaced by at least 2 seconds.
- Invalid lines are ignored; duplicate ids are collapsed.
- Each capture uses the existing purchase-history fetch and backend POST path.