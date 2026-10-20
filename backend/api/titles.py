"""The title helper's one door - counts from the listings eBay returned.

The route spends one Browse search and hands its titles to
`engine/titles.py`. It adds no counting and keeps no keyword list. The
response always names the sample size (`listings_analysed`), because a table
without one would look like a statement about eBay rather than a reading of
the listings this call actually saw.

There is deliberately no search-volume field. eBay does not give this app
one, and an invented number would be worse than a missing one.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/titles")
def title_counts(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=50),
):
    """Count words and adjacent pairs in the titles this query returned.

    One Browse search, with no price band: the helper describes the titles
    for a query, not the slice of them inside the user's active buying range.
    The New-only condition gate still applies, because that is the product's
    standing rule.

    A zero is a measured zero only when eBay answered with no listings. A
    search that could not be made is a refusal with a sentence, never an
    empty table that a reader could mistake for "nothing exists".
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be blank")

    from config import EBAY_CLIENT_ID, EBAY_CLIENT_SECRET

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail=(
                "eBay API credentials are not configured, so no listings "
                "could be fetched and no title counts were produced."
            ),
        )

    from engine.titles import analyse_titles
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    try:
        listings = scraper.search_titles(query, limit=limit)
    except Exception as exc:  # noqa: BLE001 - the route must say why it is empty
        logger.warning("title search failed for %r: %s", query, exc)
        raise HTTPException(
            status_code=502,
            detail=(
                "eBay did not answer the title search, so no listings were "
                "analysed and no counts were produced."
            ),
        ) from exc
    finally:
        scraper.close()

    result = analyse_titles(
        [getattr(listing, "title", "") for listing in listings]
    )
    payload = {"query": query, **result}
    payload["reason"] = (
        None
        if result["listings_analysed"]
        else (
            "eBay returned no active New listings for this query, so there "
            "are no title counts to report."
        )
    )
    return payload
