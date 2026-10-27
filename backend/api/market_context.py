"""FastAPI glue for the Phase J marketplace registry.

The browser sends `X-EBay-Marketplace`; a direct caller may send
`?marketplace=EBAY_US`. One function reads both, validates the id and returns
the registry record. It is deliberately an explicit helper rather than a
middleware: a route that supports a market asks for it, and a route that does
not support one keeps its UK behaviour instead of silently changing site.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from marketplaces import (
    MARKETPLACE_HEADER,
    MARKETPLACE_QUERY,
    UnknownMarketplace,
    get_marketplace,
)


def marketplace_for_request(request: Request) -> dict:
    """The requested market, or EBAY_GB; an unknown id is a 422."""
    requested = request.query_params.get(MARKETPLACE_QUERY)
    if not requested:
        requested = request.headers.get(MARKETPLACE_HEADER)
    try:
        return get_marketplace(requested)
    except UnknownMarketplace as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def marketplace_for_optional_request(request: Request | None) -> dict:
    """The route helper, with the direct-call default of the UK market.

    FastAPI always injects `Request`; a unit test calling a route function
    directly passes no request. That path is the historical UK behaviour, not
    an unvalidated market guess.
    """
    if request is None:
        return get_marketplace()
    return marketplace_for_request(request)


def require_uk_market(market: dict, surface: str) -> None:
    """Refuse a supplier-comparison surface on a non-UK marketplace.

    Analyze has a search-only path because it can return an eBay listing and
    demand picture without pricing a resale. Deep Search, Bulk, Category Hunter
    and the fee calculator cannot: each mixes eBay prices with GBP supplier
    costs and/or the UK fee card. Running them under a USD/EUR/AUD/CAD heading
    would either add across currencies or attach a GBP fee to a foreign sale,
    so they say plainly that they are UK-only.
    """
    if market["id"] == "EBAY_GB":
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"{surface} compares eBay prices with GBP supplier costs and uses "
            "the eBay UK fee table, so it is UK-only. Switch the marketplace "
            "to United Kingdom. Analyze, Deals and Titles can browse "
            f"{market['label']} without calculating a resale profit."
        ),
    )


def require_fee_market(market: dict) -> None:
    """Refuse to price a sale in a market whose calculator is not enabled.

    This is the API half of the Phase J rule. The engine's `ACTIVE_TABLE` is
    the UK card; letting a USD request fall through to it would produce a
    precise-looking number under the wrong currency. A registered card is not
    enough: EBAY_AU carries its sourced card but stays locked until Phase E5,
    so the same gate covers both "no card" and "card not enabled yet". The
    refusal carries the shared sentence rather than a bare 422.
    """
    from marketplaces import fee_calculator_ready, fee_warning

    if fee_calculator_ready(market):
        return
    raise HTTPException(status_code=422, detail=fee_warning(market))
