# Deep Search observation wiring

Deep Search and Bulk now save a reduced observation set from the eBay rows
they already read. No extra eBay API call is made.

Behavior:

- Each Deep Search run stores listing observations and one query observation.
- Bulk inherits this through `deep_search_fast()`.
- Foreign or unusable rows are skipped.
- Save failures are logged and never fail the search.
- The payload is reduced compared with Analyze because Deep Search uses sold
  data rather than the full Browse extractor.