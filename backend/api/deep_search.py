"""Deep search endpoints — full (LLM) and fast (no LLM)."""

import logging

from fastapi import APIRouter

from api.schemas import DeepSearchRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/deep-search")
def deep_search(req: DeepSearchRequest):
    """Full deep research: web search + Ollama LLM (slow, minutes)."""
    from deep_search import deep_search_product

    result = deep_search_product(req.query)
    return result.to_dict()


@router.post("/deep-search/fast")
def deep_search_fast(req: DeepSearchRequest):
    """Fast deep research: eBay sold + key supplier scrapes, NO LLM (~15s)."""
    from deep_search import deep_search_fast as _fast

    result = _fast(req.query)
    return result.to_dict()
