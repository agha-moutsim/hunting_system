"""
Shared analysis pipeline — extracted from app.py so both Streamlit and
FastAPI call the exact same logic (single source of truth).

No Streamlit imports in this module.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from config import MAX_SUPPLIERS
from db.database import SessionLocal
from db.queries import (
    save_product,
    save_demand_data,
    save_supplier_match_data,
    save_analysis_data,
    save_verdict_data,
)
from engine.decisions import DecisionEngine, Verdict as VerdictData
from engine.condition_gate import condition_passes, filter_products_by_condition
from engine.price_gate import (
    PRICE_MIN, PRICE_MAX, band_label, excluded_note,
    filter_products, in_band, over_band_reason,
)
from engine.match import TIER_NO_MATCH, compute_match
from engine.scorecard import format_scorecard
from engine.source_type import supplier_type
from engine.stores import resolve_stores, store_provenance_block
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

# ★ Freshness window (P5): a purchase-history capture is only trusted for the
# 7-day figure if it was taken within this many hours — purchase history
# moves daily, and a stale capture would silently undercount (C1/C4).
PURCHASE_HISTORY_MAX_AGE_HOURS = 24


def apply_purchase_history(
    demand: Optional[DemandDataDTO],
    ebay_url: Optional[str],
    db: Optional[Session] = None,
) -> Optional[DemandDataDTO]:
    """P5: override the 7-day demand figure with a fresh extension capture.

    Extracts the eBay item id from the analysed URL, loads the latest
    PurchaseCapture (if captured within PURCHASE_HISTORY_MAX_AGE_HOURS) and:
      * sets demand.sold_count_7d from the capture,
      * sets demand.verified_7d = True — so ONLY the Demand(7d) verdict row
        becomes verified; Demand(30d) keeps its own source's verified status,
      * appends "+purchase_history" to demand.data_source so the persisted
        demand row shows where the 7-day number came from.

    Returns `demand` unchanged when there is no id, no capture, or the
    capture is stale. `db` is an optional session (tests pass one).
    """
    if demand is None:
        return demand

    from db.queries import get_latest_purchase_capture
    from utils.purchase_history import extract_item_id

    item_id = extract_item_id(ebay_url)
    if not item_id:
        return demand

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        capture = get_latest_purchase_capture(db, item_id)
        if capture is None or capture.sold_7d is None or capture.captured_at is None:
            return demand
        age = datetime.utcnow() - capture.captured_at
        if age > timedelta(hours=PURCHASE_HISTORY_MAX_AGE_HOURS):
            logger.info(
                "Purchase-history capture for item %s is %.1fh old — ignored",
                item_id, age.total_seconds() / 3600,
            )
            return demand
        demand.sold_count_7d = capture.sold_7d
        demand.verified_7d = True
        base = demand.data_source or "ebay_sold_listings"
        if not base.endswith("+purchase_history"):
            demand.data_source = base + "+purchase_history"
        return demand
    finally:
        if own_session:
            db.close()


def _score_supplier(
    product: ScrapedProduct, reference_title: str, ebay_price: float
) -> bool:
    """C14 — score one scraped row against the eBay title; keep only a match.

    The score is computed here by code (never a constant, never the LLM's
    confidence) and written onto the row, so the DB, the API response and
    the exports all report the same number. Returns False when the matcher
    calls it "no confirmed match" — the caller drops the row (C12: fewer
    suppliers is correct; padding one in is not).

    `brand` is deliberately empty at this point: supplier search runs
    BEFORE the LLM, so no brand is known yet, and an unknown brand scores
    neutrally rather than as a mismatch.
    """
    if not reference_title:
        return True  # nothing to match against — cannot fail it either
    result = compute_match(
        reference_title,
        product.title or "",
        ebay_price=ebay_price,
        candidate_price=product.price or 0.0,
    )
    product.match_score = result.score
    product.match_tier = result.tier
    product.match_label = result.label
    product.match_basis = result.reason
    product.match_method = result.method
    if result.tier == TIER_NO_MATCH:
        logger.info(
            "Dropping supplier row '%s' (%s) — %s",
            (product.title or "")[:60], product.source, result.reason,
        )
        return False
    return True


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

    # P4 — SerpApi Google Shopping is the PRIMARY discovery source (one call,
    # at most MAX_CALLS), the seven per-supplier scrapers are the fallback.
    # Started before the gather so it costs no extra wall-clock time.
    from scrapers.serpapi_discovery import discover as serpapi_discover
    discovery_task = asyncio.ensure_future(asyncio.to_thread(serpapi_discover, query))

    pairs = await asyncio.gather(*(_run_one(name, cls) for name, cls in scrapers))

    all_results: list[ScrapedProduct] = []
    seen_urls: set[str] = set()

    def _extend(rows) -> None:
        """Append rows, dropping any URL already collected from another source."""
        for product in rows or []:
            url = (getattr(product, "url", "") or "").strip()
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            all_results.append(product)

    try:
        discovery_rows = await discovery_task
    except Exception as e:
        logger.warning("SerpApi discovery failed: %s", e)
        discovery_rows = []
    _extend(discovery_rows)
    if progress:
        icon = "✓" if discovery_rows else "–"
        progress(f"{icon} SerpApi: {len(discovery_rows)} product(s)")

    for name, results in pairs:
        icon = "✓" if results else "–"
        if progress:
            progress(f"{icon} {name}: {len(results)} product(s)")
        _extend(results)

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
        # C11 — every analysis returns a competitor-store list, even when
        # discovery found nothing. Present-but-empty + an UNVERIFIED stamp
        # is the honest answer; an absent key would read as "not applicable".
        "ebay_stores": [],
        "ebay_stores_provenance": store_provenance_block([]),
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
            except ValueError as e:
                # C10 — a Used/unknown-condition URL is refused here, before
                # demand, suppliers or the LLM are touched.
                results["errors"].append(str(e))
                _report("✗ " + str(e))
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
            # C10 — drop non-New BEFORE price selection so we pick the first
            # listing that is both in-band and New, instead of analysing a
            # Used row and refusing it at Step 5.
            new_results, excluded_non_new = filter_products_by_condition(search_results)
            if not new_results:
                results["errors"].append(
                    f'No NEW eBay listing for "{query}" — only new listings qualify.'
                )
                _report("✗ No NEW listing found")
                return results
            # PR-3 Case B: first listing INSIDE the band; never result #1 blindly.
            in_band_results, excluded_results = filter_products(new_results)
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
            if excluded_non_new:
                results["errors"].append(
                    f"⚠️ {excluded_non_new} non-New eBay result(s) excluded (C10)."
                )
                _report(f"– {excluded_non_new} non-New result(s) excluded")

        # C10 — condition gate runs BEFORE demand, suppliers and LLM spend.
        # A non-New listing is refused here; it is never carried to Step 5.
        if not condition_passes(ebay_product.condition):
            reason = (
                f"This listing is '{getattr(ebay_product, 'condition', '') or 'unknown condition'}' "
                f"— only NEW listings qualify."
            )
            results["errors"].append(reason)
            _report("✗ " + reason)
            return results

        results["ebay_product"] = ebay_product
        _report(f"✓ Found: {ebay_product.title[:60]}")

        # Step 2: Get demand data
        _report("Step 2/5 — Fetching demand data…")
        search_term = ebay_product.title if not is_url else query
        demand = ebay.get_sold_data(search_term)
        # P5: verified 7-day figure from the browser purchase-history capture
        # (single-item analysis only — one item id per analysed URL).
        demand = apply_purchase_history(demand, ebay_product.url)
        results["demand"] = demand

        # C11 — competitor stores for Analyze AND URL-hunt.
        # `resolve_stores` prefers data this run ALREADY holds (the sold
        # query above populates demand.top_sellers), and only spends a
        # request when that yielded no sellers — so the common case costs
        # nothing extra. Network failure degrades to [] + UNVERIFIED, never
        # an exception that kills the analysis.
        try:
            stores = resolve_stores(demand=demand, query=search_term)
        except Exception as e:  # noqa: BLE001 — stores are additive, not load-bearing
            logger.warning("Store discovery failed (non-fatal): %s", e)
            stores = []
        results["ebay_stores"] = stores
        results["ebay_stores_provenance"] = store_provenance_block(stores)

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
        # Supplier prices are never range-gated (PR-1) — keep usable rows as-is.
        supplier_results = [s for s in supplier_results if s.price and s.price > 0]
        # C14/C12 — retrieved is not the same as matching. Each surviving row
        # is scored against the eBay title by the deterministic matcher; a
        # row the matcher cannot place above the threshold is dropped, never
        # shown. Match fields land on the row so every later consumer (LLM,
        # DB, API response) sees the same computed number.
        supplier_results = [
            s for s in supplier_results
            if _score_supplier(s, ebay_product.title, ebay_product.price or 0.0)
        ]
        # C12 — a ceiling, never a target. Rank by how confidently the matcher
        # identified the product, then by price, and keep at most 7. Sorting
        # also makes `supplier_results[0]` (used for best_supplier_price
        # below) the strongest confirmed match instead of whichever scraper
        # happened to answer first.
        supplier_results.sort(
            key=lambda s: (-s.match_score, s.price or 0.0)
        )
        supplier_results = supplier_results[:MAX_SUPPLIERS]
        results["supplier_matches"] = supplier_results
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
            for s in supplier_results[:MAX_SUPPLIERS]
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
        supplier_delivery_days = (
            supplier_results[0].delivery_days_max if supplier_results else None
        )
        if llm_result and getattr(llm_result, "brand_name", ""):
            ebay_product.brand = llm_result.brand_name
        engine = DecisionEngine(filters=filters)
        verdict = engine.evaluate(
            ebay_product, demand, best_supplier_price, supplier_delivery_days
        )
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

        for s in suppliers[:MAX_SUPPLIERS]:
            save_supplier_match_data(db, product_id, {
                "supplier_name": s.source,
                "supplier_url": s.url,
                "supplier_title": s.title,
                "supplier_price": s.price,
                "delivery_days_min": s.delivery_days_min,
                "delivery_days_max": s.delivery_days_max,
                # C13 — these three used to be hard-coded constants
                # ("dropship", "medium", 0.5) written as if they were
                # measurements. Type is now derived from the real source
                # URL; confidence and score are left NULL because no
                # matcher has run at this point (P4 supplies one) and an
                # unknown value must not be shown as a known one (C1).
                "supplier_type": supplier_type(name=s.source, url=s.url),
                "confidence": None,
                "match_score": None,
                # We read this row off a live scraper response — that IS
                # the verification, so set it explicitly rather than
                # inheriting the column default.
                "verified": True,
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
