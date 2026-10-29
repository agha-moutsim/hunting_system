"""Bulk analysis — many queries at once, fast mode only (no LLM)."""

import logging

from fastapi import APIRouter, HTTPException, Request

from api.market_context import marketplace_for_optional_request
from api.schemas import BulkRequest
from api.provenance_block import build_provenance_block
from marketplaces import analyze_ready, fee_warning, get_marketplace

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_ready_market(request: Request | None, surface: str) -> dict:
    """Bulk runs the sourcing pipeline, so it follows Analyze's readiness."""
    market = marketplace_for_optional_request(request)
    if analyze_ready(market):
        return market
    reason = fee_warning(market) or (
        "No supplier bench is registered for this marketplace."
    )
    raise HTTPException(
        status_code=422,
        detail=f"{surface} is not enabled for {market['label']}. {reason}",
    )


@router.post("/bulk")
def bulk_analyze(req: BulkRequest, request: Request = None):
    """Run deep_search_fast() for each query sequentially."""
    from deep_search import deep_search_fast

    market = _require_ready_market(request, "Bulk analysis")
    results = []
    errors = []

    for i, query in enumerate(req.queries):
        query = query.strip()
        if not query:
            continue
        try:
            # UK keeps the historical one-argument call; a non-UK run states
            # its market so the fast path follows EBAY_AU rather than GBP.
            if market["id"] == "EBAY_GB":
                result = deep_search_fast(query)
            else:
                result = deep_search_fast(query, marketplace=market["id"])
            payload = result.to_dict()
            # C13 — each DeepSearchResult carries its own provenance block,
            # same shape as the single-query endpoints and the export.
            payload["provenance"] = build_provenance_block(payload)
            results.append(payload)
        except Exception as e:
            logger.warning("Bulk item failed: %s — %s", query, e)
            errors.append({"query": query, "error": str(e)})

    return {
        "marketplace": market["id"],
        "currency": market["currency"],
        "currency_symbol": market["currency_symbol"],
        "results": results,
        "errors": errors,
        "total": len(req.queries),
        "succeeded": len(results),
    }
