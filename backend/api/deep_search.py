"""Deep search endpoints — full (LLM) and fast (no LLM)."""

import asyncio
import logging

from fastapi import APIRouter

from api.schemas import DeepSearchRequest
from api.provenance_block import build_provenance_block, unverified_stamp

router = APIRouter()
logger = logging.getLogger(__name__)

# Budgets so the UI never hangs indefinitely
FULL_TIMEOUT_S = 120.0
FAST_TIMEOUT_S = 75.0


@router.post("/deep-search")
def deep_search(req: DeepSearchRequest):
    """Full deep research: web search + Ollama LLM (bounded ~2 min)."""
    from deep_search import deep_search_product

    try:
        result = asyncio.run(
            asyncio.wait_for(_to_thread(deep_search_product, req.query), timeout=FULL_TIMEOUT_S)
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _timeout_result(req.query, FULL_TIMEOUT_S, full=True)
    return _response(result)


@router.post("/deep-search/fast")
def deep_search_fast(req: DeepSearchRequest):
    """Fast deep research: eBay sold + key supplier scrapes, NO LLM (~15-45s)."""
    from deep_search import deep_search_fast as _fast

    try:
        result = asyncio.run(
            asyncio.wait_for(_to_thread(_fast, req.query), timeout=FAST_TIMEOUT_S)
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _timeout_result(req.query, FAST_TIMEOUT_S, full=False)
    return _response(result)


def _response(result) -> dict:
    """DeepSearchResult → payload carrying the pinned provenance block (C13).

    Both success paths hand the block through build_provenance_block so a
    run that fetched nothing can never wear the same stamp as one that did.
    """
    payload = result.to_dict()
    payload["provenance"] = build_provenance_block(payload)
    return payload


async def _to_thread(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _timeout_result(query: str, seconds: float, full: bool) -> dict:
    from deep_search import DeepSearchResult

    r = DeepSearchResult(product_name=query)
    r.verdict = "PENDING"
    r.notes = (
        f"Request timed out after {int(seconds)}s. "
        + ("Try Fast mode or retry." if full else "Supplier scrapers hung — retry.")
    )
    r.filters_passed.append({
        "name": "Data",
        "passed": False,
        "actual": f"Timed out after {int(seconds)}s",
        "expected": "Completed within budget",
        "verified": False,
    })
    # C11/C13 — a timeout discovered no stores: present-but-empty, stamped
    # unverified WITH a reason (exactly what /api/analyze's timeout does).
    reason = f"deep search timed out after {int(seconds)}s"
    r.ebay_stores_provenance = unverified_stamp(reason)
    logger.error("Deep search %s timed out after %.0fs (full=%s)", query, seconds, full)
    payload = r.to_dict()
    # C13 — nothing was fetched and nothing was computed, so every block
    # in the response reads unverified WITH why.
    payload["provenance"] = build_provenance_block(payload, reason=reason)
    return payload
