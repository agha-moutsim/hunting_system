"""POST /api/analyze — full single-product analysis pipeline."""

import asyncio
import logging

from fastapi import APIRouter
from dataclasses import asdict

from api.schemas import AnalyzeRequest
from analysis_pipeline import (
    PIPELINE_TIMEOUT_S,
    run_analysis_pipeline,
    run_async,
    save_analysis_to_db,
)
from utils.filters import load_filters

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


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Run the full pipeline: eBay → demand → 7 suppliers → LLM → verdict → scorecard."""
    filters = req.filters or load_filters()

    try:
        raw = run_async(
            run_analysis_pipeline(
                req.query,
                is_url=req.is_url,
                filters=filters,
            ),
            timeout=PIPELINE_TIMEOUT_S,
        )
    except (TimeoutError, asyncio.TimeoutError):
        logger.error("Analysis pipeline exceeded %.0fs budget", PIPELINE_TIMEOUT_S)
        return {
            "ebay_product": None,
            "demand": None,
            "supplier_matches": [],
            "llm_analysis": None,
            "verdict": None,
            "scorecard": "",
            "errors": [
                f"Analysis timed out after {int(PIPELINE_TIMEOUT_S)}s. "
                "Supplier scrapers or the LLM hung — retry, or try Deep Search → Fast."
            ],
        }

    # Persist (same path Streamlit uses)
    if raw.get("ebay_product"):
        try:
            save_analysis_to_db(raw)
        except Exception as e:
            logger.warning("DB save failed (non-fatal): %s", e)

    return {
        "ebay_product": _serialize(raw.get("ebay_product")),
        "demand": _serialize(raw.get("demand")),
        "supplier_matches": _serialize(raw.get("supplier_matches")),
        "llm_analysis": _serialize(raw.get("llm_analysis")),
        "verdict": _serialize(raw.get("verdict")),
        "scorecard": raw.get("scorecard", ""),
        "errors": raw.get("errors", []),
    }
