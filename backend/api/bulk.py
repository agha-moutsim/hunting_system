"""Bulk analysis — many queries at once, fast mode only (no LLM)."""

import logging

from fastapi import APIRouter

from api.schemas import BulkRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/bulk")
def bulk_analyze(req: BulkRequest):
    """Run deep_search_fast() for each query sequentially."""
    from deep_search import deep_search_fast

    results = []
    errors = []

    for i, query in enumerate(req.queries):
        query = query.strip()
        if not query:
            continue
        try:
            result = deep_search_fast(query)
            results.append(result.to_dict())
        except Exception as e:
            logger.warning("Bulk item failed: %s — %s", query, e)
            errors.append({"query": query, "error": str(e)})

    return {
        "results": results,
        "errors": errors,
        "total": len(req.queries),
        "succeeded": len(results),
    }
