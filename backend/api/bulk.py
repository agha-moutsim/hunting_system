"""Bulk analysis — many queries at once, fast mode only (no LLM)."""

import logging

from fastapi import APIRouter, Request

from api.market_context import marketplace_for_optional_request, require_uk_market
from api.schemas import BulkRequest
from api.provenance_block import build_provenance_block

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/bulk")
def bulk_analyze(req: BulkRequest, request: Request = None):
    """Run deep_search_fast() for each query sequentially."""
    from deep_search import deep_search_fast

    require_uk_market(
        marketplace_for_optional_request(request), "Bulk analysis"
    )
    results = []
    errors = []

    for i, query in enumerate(req.queries):
        query = query.strip()
        if not query:
            continue
        try:
            result = deep_search_fast(query)
            payload = result.to_dict()
            # C13 — each DeepSearchResult carries its own provenance block,
            # same shape as the single-query endpoints and the export.
            payload["provenance"] = build_provenance_block(payload)
            results.append(payload)
        except Exception as e:
            logger.warning("Bulk item failed: %s — %s", query, e)
            errors.append({"query": query, "error": str(e)})

    return {
        "results": results,
        "errors": errors,
        "total": len(req.queries),
        "succeeded": len(results),
    }
