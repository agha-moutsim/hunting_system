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
    """Full deep research: web search + Ollama LLM (bounded ~2 min).

    A1.4 — the run gets FULL_TIMEOUT_S as ITS budget and publishes into a
    sink as it goes. asyncio cannot cancel a thread, so without both of
    those a route timeout would discard everything already fetched and
    answer with an all-zero payload.
    """
    from deep_search import deep_search_product

    sink: dict = {}
    try:
        result = asyncio.run(
            asyncio.wait_for(
                _to_thread(deep_search_product, req.query, FULL_TIMEOUT_S, sink),
                timeout=FULL_TIMEOUT_S,
            )
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _partial_or_timeout(req.query, FULL_TIMEOUT_S, sink, full=True)
    return _response(result)


@router.post("/deep-search/fast")
def deep_search_fast(req: DeepSearchRequest):
    """Fast deep research: eBay sold + key supplier scrapes, NO LLM (~15-45s)."""
    from deep_search import deep_search_fast as _fast

    sink: dict = {}
    try:
        result = asyncio.run(
            asyncio.wait_for(
                _to_thread(_fast, req.query, FAST_TIMEOUT_S, sink),
                timeout=FAST_TIMEOUT_S,
            )
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _partial_or_timeout(req.query, FAST_TIMEOUT_S, sink, full=False)
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


def _partial_or_timeout(query: str, seconds: float, sink: dict | None,
                        *, full: bool) -> dict:
    """Answer a route timeout with whatever the run had already finished.

    A1.4. ``deep_search_product`` publishes into ``sink`` between stages
    precisely so this branch has something to hand back: the run cannot be
    cancelled, so without the sink the route threw away a completed eBay
    query, its stores and every verified supplier, and answered with an
    all-zero object that looks like the product does not sell.

    The run's own stamps are kept rather than a blanket reason: what WAS
    fetched still reads verified (C13), and the timeout itself is reported
    where a timeout belongs — in ``filters_passed`` and ``notes``. Stamping
    fetched data "timed out" would trade one falsehood for another.
    """
    partial = (sink or {}).get("result")
    if partial is None:
        return _timeout_result(query, seconds, full)

    if not partial.verdict:
        partial.verdict = "PENDING"
    late = (
        f"Timed out after {int(seconds)}s — returning the work already done; "
        "later stages did not run."
    )
    partial.notes = f"{partial.notes} {late}".strip()
    partial.filters_passed.append({
        "name": "Data",
        "passed": False,
        "actual": f"Timed out after {int(seconds)}s",
        "expected": "Completed within budget",
        "verified": False,
    })
    logger.warning("Deep search %s returned PARTIAL results after %.0fs (full=%s)",
                   query, seconds, full)
    payload = partial.to_dict()
    payload["provenance"] = build_provenance_block(payload)
    return payload
