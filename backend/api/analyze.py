"""POST /api/analyze — full single-product analysis pipeline."""

import asyncio
import logging

from fastapi import APIRouter, Request
from dataclasses import asdict

from api.market_context import marketplace_for_optional_request
from api.schemas import AnalyzeRequest
from api.provenance_block import build_provenance_block, unverified_stamp
from analysis_pipeline import (
    PIPELINE_TIMEOUT_S,
    run_analysis_pipeline,
    run_async,
    save_analysis_to_db,
)
from marketplaces import fee_warning
from utils.filters import load_filters
from engine.price_gate import clamp_band

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialize(obj):
    """Convert dataclasses / unknown objects to JSON-safe values."""
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _market_only_analysis(query: str, is_url: bool, market: dict) -> dict:
    """Browse one non-UK marketplace without pretending to price a UK resale.

    The supplier bench is UK retailers and the only fee table is eBay UK's.
    Comparing a USD asking price with a GBP supplier cost, or pricing it with
    a GBP fee card, would be arithmetic across currencies. So for a market
    with no registered fee table this route returns the real eBay listing and
    the real active-listing demand picture, and no supplier rows, no profit,
    no verdict. The returned sentence says exactly that.
    """
    from engine.condition_gate import is_new
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper(market["id"])
    errors: list[str] = []
    product = None
    demand = None
    try:
        if is_url:
            try:
                product = scraper.get_details(query)
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                errors.append(f"eBay did not return that listing: {exc}")
        else:
            try:
                products = scraper.search_checked(
                    query, limit=5, price_band=None
                )
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                products = []
                errors.append(
                    f"eBay did not answer the {market['label']} search: {exc}"
                )
            else:
                new_products = [p for p in products if is_new(p.condition)]
                if new_products:
                    product = new_products[0]
                elif products:
                    errors.append(
                        f'No NEW eBay listing for "{query}" — only new listings qualify.'
                    )
                else:
                    errors.append(f'eBay returned no listing for "{query}".')

        if product is not None:
            demand = scraper.get_sold_data(
                product.title or query,
                price_band=None,
            )
    finally:
        scraper.close()

    warning = fee_warning(market)
    errors.append(
        f"{market['label']} is search-only in this build. Supplier costs are "
        "GBP and the registered fee table is eBay UK's, so no profit or "
        "verdict is calculated. " + (warning or "")
    )
    errors.append(
        f"This result is not written to History: stored analyses do not carry "
        f"a currency, and keeping {market['currency']} prices beside GBP ones "
        "would let them be compared."
    )
    return {
        "ebay_product": product,
        "demand": demand,
        "supplier_matches": [],
        "llm_analysis": None,
        "verdict": None,
        "scorecard": "",
        "errors": [e for e in errors if e],
        "ebay_stores": [],
        "ebay_stores_provenance": unverified_stamp(
            "competitor-store discovery is UK-only"
        ),
        "query_observations": scraper.query_observations,
        "timing": {},
        "budget": {},
        "marketplace": market["id"],
        "currency": market["currency"],
    }


@router.post("/analyze")
def analyze(req: AnalyzeRequest, request: Request = None):
    """Run the full pipeline: eBay → demand → 7 suppliers → LLM → verdict → scorecard."""
    market = marketplace_for_optional_request(request)
    if not market.get("fee_table"):
        raw = _market_only_analysis(req.query, req.is_url, market)
        resp = {
            "ebay_product": _serialize(raw.get("ebay_product")),
            "demand": _serialize(raw.get("demand")),
            "supplier_matches": [],
            "llm_analysis": None,
            "verdict": None,
            "scorecard": "",
            "errors": raw.get("errors", []),
            "ebay_stores": [],
            "ebay_stores_provenance": _serialize(
                raw.get("ebay_stores_provenance")
            ),
            "timing": {},
            "budget": {},
            "marketplace": market["id"],
            "currency": market["currency"],
        }
        resp["provenance"] = build_provenance_block(resp)
        return resp

    # PR-5/PR-7: thresholds may come per-request, but the price range is the
    # PERSISTED active value — selection/search gates read the same file, so
    # the verdict's Price row can never disagree with what was fetched.
    active = load_filters()
    filters = clamp_band(req.filters)
    filters["price_min"] = active["price_min"]
    filters["price_max"] = active["price_max"]

    timing_sink: dict = {}
    try:
        raw = run_async(
            run_analysis_pipeline(
                req.query,
                is_url=req.is_url,
                filters=filters,
                timing_sink=timing_sink,
            ),
            timeout=PIPELINE_TIMEOUT_S,
        )
    except (TimeoutError, asyncio.TimeoutError):
        logger.error("Analysis pipeline exceeded %.0fs budget", PIPELINE_TIMEOUT_S)
        # What the run reported before it was cancelled — normally written by
        # the pipeline's `finally`. Empty only if it died before measuring
        # anything, which is itself the honest answer.
        timing = timing_sink.get("timing") or {}
        budget = dict(timing_sink.get("budget") or {})
        # The budget was blown by definition — that is why we are here.
        budget["budget_s"] = PIPELINE_TIMEOUT_S
        budget["overrun"] = True
        budget.setdefault("total_s", None)
        budget.setdefault("unaccounted_s", None)
        resp = {
            "ebay_product": None,
            "demand": None,
            "supplier_matches": [],
            "llm_analysis": None,
            "verdict": None,
            "scorecard": "",
            # C11 — a timeout discovered no stores; say so rather than
            # omitting the key (an absent list would read as "not applicable").
            "ebay_stores": [],
            "ebay_stores_provenance": unverified_stamp("analysis timed out"),
            # Phase 0 — the run was cut off, so it never returned. Anything
            # in `timing` was measured before the cancellation; an empty block
            # means it died before it could measure. Either way we invent
            # nothing — a fabricated per-step number is exactly the failure
            # C13 exists to prevent.
            "timing": _serialize(timing),
            "budget": _serialize(budget),
            "errors": [
                f"Analysis timed out after {int(PIPELINE_TIMEOUT_S)}s. "
                "Supplier scrapers or the LLM hung — retry, or try Deep Search → Fast."
            ],
            "marketplace": market["id"],
            "currency": market["currency"],
        }
        # C13 — a run that never completed: every block reads unverified WITH why.
        resp["provenance"] = build_provenance_block(resp, reason="analysis timed out")

        # Phase G - the search may have completed before a supplier or model
        # hang. That result set is real evidence even though the analysis did
        # not finish, so persist it here; the ordinary save below never runs.
        # An empty list means no search completed, and writes nothing.
        completed_searches = timing_sink.get("query_observations") or []
        if completed_searches:
            try:
                save_analysis_to_db(
                    {
                        "ebay_product": None,
                        "query_observations": completed_searches,
                    }
                )
            except Exception as e:  # noqa: BLE001 - reported, never raised
                logger.warning(
                    "DB save of timed-out search observation failed "
                    "(non-fatal): %s",
                    e,
                )
        return resp

    # Persist. Phase G - a query that returned no usable product still ran a
    # real Browse search, and its result set is evidence the churn page needs;
    # save_analysis_to_db handles that no-product case itself.
    if raw.get("ebay_product") or raw.get("query_observations"):
        try:
            save_analysis_to_db(raw)
        except Exception as e:
            logger.warning("DB save failed (non-fatal): %s", e)

    resp = {
        "ebay_product": _serialize(raw.get("ebay_product")),
        "demand": _serialize(raw.get("demand")),
        "supplier_matches": _serialize(raw.get("supplier_matches")),
        "llm_analysis": _serialize(raw.get("llm_analysis")),
        "verdict": _serialize(raw.get("verdict")),
        "scorecard": raw.get("scorecard", ""),
        "errors": raw.get("errors", []),
        # C11 — competitor stores, same shape for Analyze and URL-hunt.
        "ebay_stores": _serialize(raw.get("ebay_stores") or []),
        "ebay_stores_provenance": _serialize(
            raw.get("ebay_stores_provenance")
            # C13 — an unstamped block must still say WHY it reads unverified.
            or unverified_stamp("store discovery recorded no stamp")
        ),
        # Phase 0 — where the seconds went, carried through untouched.
        "timing": _serialize(raw.get("timing")) or {},
        "budget": _serialize(raw.get("budget")) or {},
        # Phase J — which market produced these rows, and the currency every
        # eBay price in them is denominated in.
        "marketplace": market["id"],
        "currency": market["currency"],
    }
    # C13 — the pinned top-level block: every section stamped, nothing assumed.
    resp["provenance"] = build_provenance_block(resp)
    return resp
