"""
Shared analysis pipeline — extracted from app.py so both Streamlit and
FastAPI call the exact same logic (single source of truth).

No Streamlit imports in this module.
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.queries import (
    save_product,
    save_demand_data,
    save_supplier_match_data,
    save_analysis_data,
    save_verdict_data,
)
from engine.decisions import DecisionEngine, Verdict as VerdictData
from engine.price_gate import (
    PRICE_MIN, PRICE_MAX, band_label, excluded_note,
    filter_products, in_band, over_band_reason,
)
from engine.scorecard import format_scorecard
from llm.analyzer import ProductAnalyzer, LLMAnalysis
from scrapers.ebay import EbayScraper
from scrapers.base import ScrapedProduct, DemandData as DemandDataDTO

logger = logging.getLogger(__name__)


def run_async(coro, timeout: float | None = None):
    """Run an async coroutine from synchronous code (optional hard timeout)."""
    loop = asyncio.new_event_loop()
    try:
        if timeout is None:
            return loop.run_until_complete(coro)
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        loop.close()


# Cap concurrent Playwright browsers — 7 full Chromium instances
# thrash the machine and can OOM/kill the API process.
_BROWSER_SEMAPHORE = asyncio.Semaphore(2)
# Hard cap per supplier scraper so one hung site can't stall the pipeline.
SCRAPER_TIMEOUT_S = 45.0
# Overall pipeline budget (eBay + suppliers + LLM + verdict).
PIPELINE_TIMEOUT_S = 150.0


async def search_all_suppliers(query: str, progress=None) -> list[ScrapedProduct]:
    """Search all 7 supplier scrapers in parallel and return combined results."""
    from scrapers.aliexpress import AliExpressScraper
    from scrapers.amazon_uk import AmazonUKScraper
    from scrapers.bandq import BandQScraper
    from scrapers.cjdropshipping import CJDropshippingScraper
    from scrapers.godropship import GoDropshipScraper
    from scrapers.joybuy import JoybuyScraper
    from scrapers.toolstation import ToolstationScraper

    scrapers = [
        ("AliExpress", AliExpressScraper),
        ("Amazon UK", AmazonUKScraper),
        ("CJ Dropshipping", CJDropshippingScraper),
        ("GoDropship", GoDropshipScraper),
        ("Joybuy", JoybuyScraper),
        ("B&Q", BandQScraper),
        ("Toolstation", ToolstationScraper),
    ]

    async def _run_one(name: str, ScraperClass):
        scraper = ScraperClass()
        try:
            async with _BROWSER_SEMAPHORE:
                results = await asyncio.wait_for(
                    scraper.search(query), timeout=SCRAPER_TIMEOUT_S
                )
            return name, results
        except asyncio.TimeoutError:
            logger.warning("Supplier search timed out for %s (%.0fs)", name, SCRAPER_TIMEOUT_S)
            return name, []
        except Exception as e:
            logger.warning("Supplier search failed for %s: %s", name, e)
            return name, []
        finally:
            try:
                await asyncio.wait_for(scraper.close(), timeout=5.0)
            except Exception:
                pass

    pairs = await asyncio.gather(*(_run_one(name, cls) for name, cls in scrapers))

    all_results: list[ScrapedProduct] = []
    for name, results in pairs:
        icon = "✓" if results else "–"
        if progress:
            progress(f"{icon} {name}: {len(results)} product(s)")
        all_results.extend(results)

    all_results.sort(key=lambda p: p.price)
    return all_results


async def run_analysis_pipeline(
    query: str,
    is_url: bool = False,
    progress=None,
    filters: dict | None = None,
) -> dict:
    """Execute the full analysis: scrape eBay → suppliers → LLM → verdict."""

    def _report(msg: str):
        if progress:
            progress(msg)

    ebay = EbayScraper()
    results = {
        "ebay_product": None,
        "demand": None,
        "supplier_matches": [],
        "llm_analysis": None,
        "verdict": None,
        "scorecard": "",
        "errors": [],
    }

    try:
        # Step 1: Get eBay product — price band gate (CONSTRAINTS_PRICING.md PR-2)
        _report("Step 1/5 — Searching eBay…")
        if is_url:
            # Hard budget: item-token fallbacks must not blow the stage (README invariant)
            try:
                ebay_product = await asyncio.wait_for(
                    asyncio.to_thread(ebay.get_details, query), timeout=25.0
                )
            except asyncio.TimeoutError:
                logger.warning("eBay URL lookup exceeded 25s budget")
                results["errors"].append(
                    "eBay listing lookup timed out (25s) — retry, or try Deep Search → Fast."
                )
                return results
            # PR-3 Case A: over-band URL refuses before any further work.
            if not in_band(ebay_product.price):
                results["errors"].append(over_band_reason(ebay_product.price))
                _report("✗ " + over_band_reason(ebay_product.price))
                return results
        else:
            search_results = ebay.search(query, limit=5)
            if not search_results:
                results["errors"].append(
                    "eBay requires API keys to search. "
                    "Get free keys at https://developer.ebay.com and add them to .env"
                )
                return results
            # PR-3 Case B: first listing INSIDE the band; never result #1 blindly.
            in_band_results, excluded_results = filter_products(search_results)
            if not in_band_results:
                # PR-3 Case C: honest empty result, never an out-of-band guess.
                results["errors"].append(
                    f'No eBay listing for "{query}" found in the {band_label()} band.'
                )
                _report(f"✗ No listing in the {band_label()} band")
                return results
            ebay_product = in_band_results[0]
            # PR-4: discarded search results are counted, never silent
            if excluded_results:
                note = excluded_note("eBay search results", excluded_results)
                results["errors"].append(f"⚠️ {note}")
                _report(f"– {note}")

        results["ebay_product"] = ebay_product
        _report(f"✓ Found: {ebay_product.title[:60]}")

        # Step 2: Get demand data
        _report("Step 2/5 — Fetching demand data…")
        search_term = ebay_product.title if not is_url else query
        demand = ebay.get_sold_data(search_term)
        results["demand"] = demand
        if demand and demand.sold_count_30d:
            _report(f"✓ Demand: {demand.sold_count_30d} sold in 30 days")
        else:
            _report("– No demand counts available (marked Unverified)")
        if demand and getattr(demand, "excluded_over_band", 0):
            note = excluded_note("sold listings", demand.excluded_over_band)
            results["errors"].append(f"⚠️ {note}")
            _report(f"– {note}")

        # Step 3: Search suppliers
        _report("Step 3/5 — Searching 7 suppliers (max ~45s each, 2 at a time)…")
        try:
            supplier_results = await asyncio.wait_for(
                search_all_suppliers(ebay_product.title, progress=_report),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Supplier search budget exceeded (90s) — continuing with partial/empty")
            results["errors"].append(
                "⚠️ Supplier search timed out (90s) — results may be incomplete (Unverified)."
            )
            supplier_results = []
        # PR-2 layer 3 / PR-4: drop out-of-band supplier rows, report the count.
        supplier_results, excluded_suppliers = filter_products(supplier_results)
        results["supplier_matches"] = supplier_results
        if excluded_suppliers:
            note = excluded_note("supplier matches", excluded_suppliers)
            results["errors"].append(f"⚠️ {note}")
            _report(f"– {note}")
        _report(f"✓ Supplier search done: {len(supplier_results)} total matches")

        # Step 4: LLM analysis
        _report("Step 4/5 — Running AI analysis (llama3.1)…")
        supplier_dicts = [
            {
                "name": s.title[:60],
                "price": s.price,
                "delivery_days": s.delivery_days_max or "?",
                "source": s.source,
            }
            for s in supplier_results[:5]
        ]
        demand_dict = {
            "sold_count_30d": demand.sold_count_30d,
            "sold_count_7d": demand.sold_count_7d,
            "avg_sold_price": demand.avg_sold_price,
            "lowest_sold_price": demand.lowest_sold_price,
            "highest_sold_price": demand.highest_sold_price,
        }
        product_dict = {
            "title": ebay_product.title,
            "price": ebay_product.price,
            "condition": ebay_product.condition,
            "seller": ebay_product.seller or "Unknown",
        }

        analyzer = ProductAnalyzer()
        try:
            llm_result = await asyncio.wait_for(
                analyzer.analyze(product_dict, demand_dict, supplier_dicts),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM analysis timed out (45s) — using unverified defaults")
            results["errors"].append(
                "⚠️ AI analysis timed out — brand/demand marked Unverified."
            )
            from llm.analyzer import UNVERIFIED_DEFAULT
            llm_result = UNVERIFIED_DEFAULT
        finally:
            try:
                await analyzer.close()
            except Exception:
                pass
        results["llm_analysis"] = llm_result
        if llm_result:
            _report(
                f"✓ AI verdict: {llm_result.brand_verdict} brand, "
                f"{llm_result.demand_assessment} demand → {llm_result.recommended_action}"
            )
        else:
            _report("– AI analysis unavailable (Ollama offline)")

        # Step 5: Decision verdict
        _report("Step 5/5 — Applying business rules and profit calculation…")
        best_supplier_price = supplier_results[0].price if supplier_results else None
        engine = DecisionEngine(filters=filters)
        verdict = engine.evaluate(ebay_product, demand, best_supplier_price)
        results["verdict"] = verdict
        if verdict:
            _report(f"✓ Verdict: {verdict.verdict.upper()}")

        # Step 6: Scorecard
        scorecard = format_scorecard(ebay_product, supplier_results, demand, verdict)
        results["scorecard"] = scorecard

    except Exception as e:
        logger.exception("Analysis pipeline failed")
        results["errors"].append(str(e))
    finally:
        ebay.close()

    return results


def save_analysis_to_db(results: dict):
    """Persist analysis results to the database."""
    db: Session = SessionLocal()
    try:
        ebay_product: ScrapedProduct = results["ebay_product"]
        demand: DemandDataDTO = results["demand"]
        suppliers: list[ScrapedProduct] = results["supplier_matches"]
        llm: Optional[LLMAnalysis] = results["llm_analysis"]
        verdict: Optional[VerdictData] = results["verdict"]

        if not ebay_product:
            return

        product_id = save_product(db, ebay_product)

        if demand:
            save_demand_data(db, product_id, demand)

        for s in suppliers[:5]:
            save_supplier_match_data(db, product_id, {
                "supplier_name": s.source,
                "supplier_url": s.url,
                "supplier_title": s.title,
                "supplier_price": s.price,
                "delivery_days_min": s.delivery_days_min,
                "delivery_days_max": s.delivery_days_max,
                "supplier_type": "dropship",
                "confidence": "medium",
                "match_score": 0.5,
            })

        if llm:
            save_analysis_data(db, product_id, {
                "brand_verdict": llm.brand_verdict,
                "brand_reasoning": llm.brand_reasoning,
                "demand_assessment": llm.demand_assessment,
                "demand_reasoning": llm.demand_reasoning,
                "supplier_match_notes": llm.supplier_type_reasoning,
                "llm_raw_response": llm.raw_response,
            })

        if verdict:
            save_verdict_data(db, product_id, {
                "verdict": verdict.verdict,
                "profit_amount": verdict.profit,
                "profit_margin": verdict.margin,
                "filter_results": [
                    {"name": f.name, "passed": f.passed, "actual": f.actual, "expected": f.expected}
                    for f in verdict.filters
                ],
                "scorecard": results.get("scorecard", ""),
            })

        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to save to database: %s", e)
    finally:
        db.close()
