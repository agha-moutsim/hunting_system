"""Run saved searches through the Hunter fast path, with a stated budget.

Phase E. A saved search is a query someone asked to have re-checked; the
app's measurement of a query is the deep-search fast path - the same
analysis one manual Hunt on that query spends - whose eBay stage calls the
Browse search endpoint once (scrapers/ebay_sold). So the cost of a pass is
countable BEFORE it happens, and this module states it rather than letting
the stored list decide: a pass runs at most `MAX_SEARCHES_PER_PASS`
searches, that is 10 Browse calls against the 5,000/day allowance, and the
report says how much was spent and how much was deliberately NOT run.

What earns a row (`search_results`): only a result whose numbers are all
real - a named listing URL, an eBay asking price, a supplier price, a
positive profit, and a margin that clears the search's own minimum, inside
the search's own price band. Anything less gets no row and the reason is
returned in the report; an empty night is stored as an empty night, never
as a cheap find.

One implementation: `watchlist.runner` re-exports run_search/run_all_searches
from here, so a run from the Watchlist page and a scheduled pass write
identical rows with identical cost.
"""

from datetime import datetime
from typing import Optional


#: A pass runs at most this many searches - the stated Browse budget. One
#: search spends one Browse call, so a full pass costs 10 calls (0.2% of the
#: 5,000/day allowance).
MAX_SEARCHES_PER_PASS = 10

#: Per-search time budget for the analysis (seconds). The fast path runs in
#: seconds; this stops one pathological query holding the whole pass.
DEFAULT_SEARCH_BUDGET_S = 30.0


def _why_no_row(search, result) -> Optional[str]:
    """Why this analysis earned no row - None when it earned one.

    Every sentence names the value that failed; there is no silent skip, so
    a run report can always say why the inbox did not grow.
    """
    from utils.filters import active_range, price_in_range, resolve_range, valid_range

    url = result.sources[0] if result.sources else ""
    if not url:
        return "the analysis named no specific listing, and a match nobody can open is not a match"

    avg_price = result.ebay_avg_price or 0.0
    supplier_price = result.best_supplier_price or 0.0
    if avg_price <= 0:
        return "the analysis found no eBay asking price to compare"
    if supplier_price <= 0:
        return "no real supplier price was found, so a margin would be a guess"

    view = (
        resolve_range(search.price_min, search.price_max)
        if valid_range(search.price_min, search.price_max)
        else active_range()
    )
    if not price_in_range(avg_price, view):
        return (
            f"the eBay price £{avg_price:.2f} is outside this search's band "
            f"£{view['min']:.2f}-£{view['max']:.2f}"
        )

    if (result.profit or 0.0) <= 0:
        return (
            f"the profit at the supplier price found is £{(result.profit or 0.0):.2f}, "
            f"which is not a find"
        )

    margin = result.margin or 0.0
    minimum = search.min_margin if search.min_margin is not None else 0.0
    if margin < minimum:
        return (
            f"the margin {margin:.1f}% is below this search's own minimum "
            f"{minimum:.1f}%"
        )
    return None


def run_saved_search(
    search_id: int, *, budget_s: float = DEFAULT_SEARCH_BUDGET_S
) -> dict:
    """Run one saved search and store what qualifies.

    Returns a report: `found` (rows written), `error` (a set-up problem or a
    failed analysis), `reason` (why nothing was stored when nothing was),
    and `browse_calls` (the stated cost of this run: 1 when the analysis
    ran, 0 when the run never got that far).
    """
    from db.database import SessionLocal
    from db.models import SavedSearch, SearchResult

    db = SessionLocal()
    try:
        search = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if search is None:
            return {
                "found": 0,
                "error": "Search not found",
                "reason": None,
                "browse_calls": 0,
            }

        query = (search.query or "").strip()
        if not query:
            search.last_run = datetime.utcnow()
            db.commit()
            return {
                "found": 0,
                "error": None,
                "reason": "the search has no query, so there is nothing to run",
                "browse_calls": 0,
            }

        from deep_search import deep_search_fast

        try:
            result = deep_search_fast(query, budget_s=budget_s)
        except Exception as e:
            search.last_run = datetime.utcnow()
            db.commit()
            return {
                "found": 0,
                "error": f"analysis failed: {e}",
                "reason": None,
                "browse_calls": 1,
            }

        url = result.sources[0] if result.sources else ""

        report = {"found": 0, "error": None, "reason": None, "browse_calls": 1}

        reason = _why_no_row(search, result)
        if reason is not None:
            report["reason"] = reason
        else:
            existing = (
                db.query(SearchResult)
                .filter(
                    SearchResult.search_id == search_id,
                    SearchResult.ebay_url == url,
                )
                .first()
            )
            if existing is not None:
                report["reason"] = "this listing is already in the results"
            else:
                supplier_url = ""
                supplier_name = ""
                if result.suppliers:
                    supplier_url = result.suppliers[0].get("url", "")
                    supplier_name = result.suppliers[0].get("name", "")

                db.add(
                    SearchResult(
                        search_id=search_id,
                        product_name=result.product_name,
                        ebay_url=url,
                        ebay_price=result.ebay_avg_price,
                        supplier_price=result.best_supplier_price,
                        supplier_url=supplier_url,
                        supplier_name=supplier_name,
                        profit=result.profit,
                        margin=result.margin,
                        verdict=result.verdict,
                    )
                )
                report["found"] = 1

        # `last_run` is a fact about the search, not about success: a run
        # that found nothing still happened, and the page must say when.
        search.last_run = datetime.utcnow()
        db.commit()
        return report
    finally:
        db.close()


def run_saved_searches(
    *,
    max_searches: int = MAX_SEARCHES_PER_PASS,
    budget_s: float = DEFAULT_SEARCH_BUDGET_S,
    progress_callback=None,
) -> dict:
    """Run the auto-run saved searches, up to the stated pass budget.

    The budget is a hard stop, not an estimate: with more searches stored
    than `max_searches`, the pass reports how many it did NOT run rather
    than quietly spending more of the allowance.
    """
    from db.database import SessionLocal
    from db.models import SavedSearch

    db = SessionLocal()
    try:
        searches = (
            db.query(SavedSearch)
            .filter(SavedSearch.auto_run == True)  # noqa: E712
            .order_by(SavedSearch.id)
            .all()
        )
        stored = len(searches)
        selected = [(s.id, s.search_name) for s in searches[: max(0, int(max_searches))]]
    finally:
        db.close()

    total_found = 0
    reasons: list[str] = []
    for index, (search_id, search_name) in enumerate(selected):
        if progress_callback:
            progress_callback(index, len(selected), search_name)
        report = run_saved_search(search_id, budget_s=budget_s)
        total_found += report["found"]
        if report["reason"]:
            reasons.append(f"{search_name}: {report['reason']}")

    return {
        "searches_run": len(selected),
        "searches_stored": stored,
        "searches_not_run": max(0, stored - len(selected)),
        "total_found": total_found,
        #: The stated Browse cost of this pass: one call per search that ran.
        "browse_calls": len(selected),
        "reasons": reasons,
    }
