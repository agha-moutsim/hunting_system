"""
Pipeline orchestrator — runs the full eBay product sourcing flow.

Steps:
  1. Scrape eBay (search or listing)
  2. Search all 7 suppliers in parallel
  3. LLM analysis
  4. Decision engine verdict
  5. Profit calculation for best supplier
  6. Save to database
  7. Return structured result
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, field
from datetime import datetime
from typing import Any, Optional

from config import FILTERS, MAX_SUPPLIERS
from engine.match import TIER_NO_MATCH, compute_match, image_hash_for
from db.database import SessionLocal
from db.queries import (
    save_analysis_data,
    save_demand_data,
    save_product,
    save_supplier_match_data,
    save_verdict_data,
)
from engine.decisions import DecisionEngine
from engine.profit import calculate_profit
from engine.stores import resolve_stores, store_provenance_block
from llm.analyzer import ProductAnalyzer
from scrapers.aliexpress import AliExpressScraper
from scrapers.bandq import BandQScraper
from scrapers.cjdropshipping import CJDropshippingScraper
from scrapers.ebay import EbayScraper
from scrapers.toolstation import ToolstationScraper

logger = logging.getLogger(__name__)

# GoDropship and Joybuy removed 2026-10; see suppliers.json for the evidence.
SUPPLIER_SCRAPERS = {
    "aliexpress": AliExpressScraper,
    "cjdropshipping": CJDropshippingScraper,
    "bandq": BandQScraper,
    "toolstation": ToolstationScraper,
}


def _is_ebay_url(text: str) -> bool:
    return bool(re.search(r"ebay\.\w+", text, re.IGNORECASE))


def _extract_listing_id(url: str) -> str | None:
    match = re.search(r"/itm/(\d+)", url)
    return match.group(1) if match else None


def _build_query_from_title(title: str) -> str:
    """Strip filler words to build a concise supplier search query."""
    stop = {"new", "uk", "bnib", "bnip", "rrp", "free", "fast", "post", "boxed", "sealed"}
    words = [w for w in title.split() if w.lower().strip(",.()[]!") not in stop]
    return " ".join(words[:8])


def _resolve_supplier_choice(name: Any, suppliers: list[dict]) -> dict | None:
    """Map an LLM-returned supplier name back onto a real scraped row (C12/C13).

    The model is shown a ranked list and asked to name the best match. It
    sometimes returns a plausible name that was never on that list. We only
    ever surface a choice we can bind to a row we actually retrieved —
    otherwise we return None and the caller drops it.
    """
    if not name or not suppliers:
        return None
    target = str(name).strip().lower()
    if not target:
        return None

    keys = ("name", "full_name", "source")

    # Exact (case-insensitive) first — the clean case.
    for s in suppliers:
        for key in keys:
            val = str(s.get(key, "")).strip().lower()
            if val and val == target:
                return s

    # Then containment, so "Amazon UK - Some Store" binds to "Amazon UK".
    # Length floor keeps a 1-2 char answer from matching everything.
    if len(target) >= 4:
        for s in suppliers:
            for key in keys:
                val = str(s.get(key, "")).strip().lower()
                if len(val) >= 4 and (val in target or target in val):
                    return s
    return None


def _match_gate(
    products: list,
    reference_title: str,
    ebay_price: float,
    ebay_image_hash: int | None = None,
) -> list:
    """Score each scraped row against the eBay title; keep the matches (C14).

    The computed score is written onto the row, so the dict serialised by
    `asdict()` downstream already carries what the matcher decided — no
    consumer has to recompute, and none can substitute its own number.
    With nothing to match against the rows are kept as-is: we do not fail
    evidence we were never able to test.

    `ebay_image_hash` enables C14's image phash. It is only consulted when
    both sides have an image; without a reference hash no image is fetched
    at all, and one that cannot be read stays None rather than guessed.
    """
    if not products:
        return []
    if not reference_title:
        return list(products)

    kept = []
    for p in products:
        if not p.price or p.price <= 0:
            continue
        if ebay_image_hash is not None and getattr(p, "image_hash", None) is None:
            p.image_hash = image_hash_for(getattr(p, "image_url", None))
        r = compute_match(
            reference_title,
            p.title or "",
            ebay_price=ebay_price,
            candidate_price=p.price,
            ebay_image_hash=ebay_image_hash,
            candidate_image_hash=getattr(p, "image_hash", None),
        )
        p.match_score = r.score
        p.match_tier = r.tier
        p.match_label = r.label
        p.match_basis = r.reason
        p.match_method = r.method
        if r.tier != TIER_NO_MATCH:
            kept.append(p)
    return kept


class PipelineResult:
    """Structured output returned by Pipeline.run()."""

    def __init__(self):
        self.product: dict[str, Any] = {}
        self.demand: dict[str, Any] = {}
        self.suppliers: dict[str, list[dict]] = {}
        # C11 — competitor stores, present on every surface now. `[]` means
        # "none found"; read ebay_stores_provenance for whether that is
        # VERIFIED (four real stores) or UNVERIFIED (nothing, or a widened
        # search that came up short).
        self.ebay_stores: list[dict[str, Any]] = []
        self.ebay_stores_provenance: dict[str, Any] = {}
        self.analysis: dict[str, Any] = {}
        self.verdict: dict[str, Any] = {}
        self.profit: dict[str, Any] = {}
        self.scorecard: str = ""
        self.errors: list[str] = []
        self.db_product_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "demand": self.demand,
            "suppliers": self.suppliers,
            "ebay_stores": self.ebay_stores,
            "ebay_stores_provenance": self.ebay_stores_provenance,
            "analysis": self.analysis,
            "verdict": self.verdict,
            "profit": self.profit,
            "scorecard": self.scorecard,
            "errors": self.errors,
            "db_product_id": self.db_product_id,
        }


class Pipeline:
    """Full sourcing pipeline — scrape, analyse, decide, save."""

    def __init__(self, filters: dict | None = None):
        self._ebay = EbayScraper()
        self._analyzer = ProductAnalyzer()
        self._decision = DecisionEngine(filters=filters)
        self._supplier_instances = {
            name: cls() for name, cls in SUPPLIER_SCRAPERS.items()
        }

    async def run(self, ebay_url_or_query: str) -> dict[str, Any]:
        """Execute the full pipeline and return a result dict."""
        result = PipelineResult()

        # ── Step 1: eBay scrape ────────────────────────────────────
        product, demand, query = await self._scrape_ebay(
            ebay_url_or_query, result
        )
        if not product:
            return result.to_dict()

        # C14 — hash the reference eBay image once, before it is serialised,
        # so the product itself reports the hash the matcher went on to use.
        product.image_hash = image_hash_for(getattr(product, "image_url", None))
        result.product = asdict(product)
        result.demand = asdict(demand) if demand else {}

        # C11 — competitor stores, before the verdict so the count is available
        # to the engine in step 4. Costs nothing extra when the sold response
        # already carried the sellers.
        self._attach_stores(demand, query, result)

        # ── Step 2: Search all suppliers in parallel ───────────────
        supplier_products = await self._search_suppliers(
            query, result,
            reference_title=product.title,
            ebay_price=product.price or 0.0,
            ebay_image_hash=product.image_hash,
        )
        result.suppliers = {
            k: [asdict(p) for p in v] for k, v in supplier_products.items()
        }

        # ── Step 3: LLM analysis ───────────────────────────────────
        analysis = await self._run_analysis(
            product, demand, supplier_products, result
        )

        # ── Step 4 + 5: Decision engine + profit ──────────────────
        best_supplier_price, best_supplier_name = self._evaluate_and_profit(
            product, demand, supplier_products, analysis, result
        )

        # ── Step 6: Save to database ───────────────────────────────
        self._save_to_db(
            product, demand, supplier_products, analysis, result
        )

        # ── Step 7: Build scorecard ────────────────────────────────
        result.scorecard = self._build_scorecard(
            product, demand, analysis, result
        )

        return result.to_dict()

    async def run_manual(
        self, title: str, price: float, condition: str = "New"
    ) -> dict[str, Any]:
        """Run pipeline with manual product entry (skip eBay scraping)."""
        result = PipelineResult()

        # Create product from manual input
        product = ScrapedProduct(
            source="manual",
            title=title,
            price=price,
            url="",
            condition=condition,
            verified=True,
        )
        demand = DemandData(verified=False)
        query = _build_query_from_title(title)

        # C14 — same reference hash as the run() path, taken before asdict.
        product.image_hash = image_hash_for(getattr(product, "image_url", None))
        result.product = asdict(product)
        result.demand = asdict(demand)

        # C11 — same store discovery as the run() path. A manual run has no
        # sold response to reuse, so this spends a request; it still degrades
        # to [] + UNVERIFIED rather than failing the run.
        self._attach_stores(demand, query, result)

        # Search suppliers
        supplier_products = await self._search_suppliers(
            query, result,
            reference_title=product.title,
            ebay_price=product.price or 0.0,
            ebay_image_hash=product.image_hash,
        )
        result.suppliers = {
            k: [asdict(p) for p in v] for k, v in supplier_products.items()
        }

        # LLM analysis
        analysis = await self._run_analysis(
            product, demand, supplier_products, result
        )

        # Decision + profit
        best_supplier_price, best_supplier_name = self._evaluate_and_profit(
            product, demand, supplier_products, analysis, result
        )

        # Save to DB
        self._save_to_db(product, demand, supplier_products, analysis, result)

        # Scorecard
        result.scorecard = self._build_scorecard(
            product, demand, analysis, result
        )

        return result.to_dict()

    # ================================================================
    # Step 1 — eBay
    # ================================================================

    async def _scrape_ebay(
        self, input_text: str, result: PipelineResult
    ):
        """Scrape eBay from URL or search query. Returns (product, demand, query)."""
        try:
            if _is_ebay_url(input_text):
                product = await asyncio.to_thread(
                    self._ebay.get_details, input_text
                )
                if not product or not product.title:
                    result.errors.append("eBay listing scrape returned empty")
                    return None, None, ""
                query = _build_query_from_title(product.title)
            else:
                query = input_text
                results = await asyncio.to_thread(
                    self._ebay.search, input_text, 1
                )
                if not results:
                    result.errors.append(
                        "eBay search returned no results. "
                        "Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to .env to enable eBay API access."
                    )
                    return None, None, query
                product = results[0]

            # Fetch demand data
            demand = await asyncio.to_thread(
                self._ebay.get_sold_data, query
            )
            return product, demand, query

        except Exception as e:
            logger.exception("eBay step failed")
            result.errors.append(f"eBay scrape failed: {e}")
            return None, None, ""

    # ================================================================
    # Step 2 — Supplier search (parallel)
    # ================================================================

    async def _search_suppliers(
        self,
        query: str,
        result: PipelineResult,
        reference_title: str = "",
        ebay_price: float = 0.0,
        ebay_image_hash: int | None = None,
    ) -> dict[str, list]:
        """Search all 7 suppliers concurrently.

        C14 runs here too: every row the scrapers return is scored against
        the eBay title, and rows the matcher calls "no confirmed match" are
        dropped before they can reach profit or the LLM (C12 — a short list
        is correct; a padded one is not).
        """

        async def _run_one(name: str, scraper) -> tuple[str, list]:
            try:
                products = await scraper.search(query)
            except Exception as e:
                logger.warning("Supplier %s failed: %s", name, e)
                result.errors.append(f"Supplier {name} failed: {e}")
                return name, []
            return name, _match_gate(products, reference_title, ebay_price, ebay_image_hash)

        tasks = [
            _run_one(name, scraper)
            for name, scraper in self._supplier_instances.items()
        ]
        pairs = await asyncio.gather(*tasks)
        # C12 — a ceiling across ALL sources, never a target. Rank by match
        # strength then price so the survivors are the strongest confirmed
        # identities rather than whichever scraper answered first.
        flat = sorted(
            (p for _, products in pairs for p in products),
            key=lambda p: (-getattr(p, "match_score", 0.0), p.price or 0.0),
        )[:MAX_SUPPLIERS]
        by_source: dict[str, list] = {name: [] for name, _ in pairs}
        for p in flat:
            by_source[p.source] = by_source.get(p.source, []) + [p]
        return by_source

    # ================================================================
    # Step 3 — LLM analysis
    # ================================================================

    async def _run_analysis(
        self,
        product,
        demand,
        supplier_products: dict[str, list],
        result: PipelineResult,
    ):
        """Run the ProductAnalyzer and store the result."""
        try:
            # Flatten top supplier matches for the LLM
            supplier_dicts = []
            for name, products in supplier_products.items():
                for p in products[:3]:  # top 3 per supplier
                    supplier_dicts.append({
                        "source": name,
                        "title": p.title,
                        "price": p.price,
                        "url": p.url,
                        "delivery_days_min": p.delivery_days_min,
                        "delivery_days_max": p.delivery_days_max,
                    })

            analysis = await self._analyzer.analyze(
                product=asdict(product),
                demand=asdict(demand) if demand else {},
                suppliers=supplier_dicts,
            )
            result.analysis = {
                "brand_verdict": analysis.brand_verdict,
                "brand_reasoning": analysis.brand_reasoning,
                "demand_assessment": analysis.demand_assessment,
                "demand_reasoning": analysis.demand_reasoning,
                "supplier_type": analysis.supplier_type,
                "supplier_type_reasoning": analysis.supplier_type_reasoning,
                "recommended_action": analysis.recommended_action,
                "risk_flags": analysis.risk_flags,
                "parse_success": analysis.parse_success,
            }
            if analysis.best_supplier_match:
                # C12/C13 — verify-or-drop. The model was shown a ranked list
                # and returns a NAME it says is the best match. A name that
                # is not on that list is an invention, so we resolve the
                # returned name against the suppliers we actually scraped;
                # no match means no row, never a plausible-looking supplier.
                resolved = _resolve_supplier_choice(
                    analysis.best_supplier_match.name, supplier_dicts
                )
                if resolved is not None:
                    result.analysis["best_supplier_match"] = {
                        # C13 — the IDENTITY claim is verified: this name and
                        # this URL come from a row we scraped ourselves.
                        "name": resolved["name"],
                        "provenance": "verified",
                        "provenance_label": "Verified",
                        "source_url": resolved.get("url", ""),
                        "source_name": resolved.get("source", ""),
                        # C13 — the MODEL'S OPINION about that supplier.
                        # Tagged ai_insight so a confidence of 0.9 can never
                        # be read as evidence the supplier was checked.
                        "confidence": analysis.best_supplier_match.confidence,
                        "reasoning": analysis.best_supplier_match.reasoning,
                        "analysis_provenance": "ai_insight",
                        "analysis_provenance_label": "AI Insight",
                    }
                else:
                    result.analysis["best_supplier_match_unresolved"] = (
                        "The model named a supplier that was not in the "
                        "retrieved set — dropped rather than displayed."
                    )
            return analysis

        except Exception as e:
            logger.exception("LLM analysis failed")
            result.errors.append(f"LLM analysis failed: {e}")
            from llm.analyzer import UNVERIFIED_DEFAULT
            return UNVERIFIED_DEFAULT

    # ================================================================
    # Steps 4 + 5 — Decision + profit
    # ================================================================

    def _attach_stores(self, demand, query: str, result: PipelineResult) -> None:
        """C11 — competitor stores, same shape as every other surface.

        `resolve_stores` prefers data this run ALREADY holds (the sold query
        populates demand.top_sellers), so the common case costs no extra
        request. A network failure degrades to [] + UNVERIFIED and is NOT
        recorded as a run error: stores are additive, and losing them must not
        cost the product its verdict.
        """
        ladder: dict[str, Any] = {}
        try:
            stores = resolve_stores(demand=demand, query=query, provenance=ladder)
        except Exception as e:  # noqa: BLE001 — additive, never load-bearing
            logger.warning("Store discovery failed (non-fatal): %s", e)
            stores = []
        result.ebay_stores = stores
        result.ebay_stores_provenance = store_provenance_block(stores, ladder)

    def _evaluate_and_profit(
        self,
        product,
        demand,
        supplier_products: dict[str, list],
        analysis,
        result: PipelineResult,
    ) -> tuple[float | None, str | None]:
        """Pick the best supplier match, run decision engine, calc profit."""
        best_price = None
        best_name = None

        # Find cheapest verified supplier with stock
        for name, products in supplier_products.items():
            for p in products:
                if p.price > 0 and p.verified:
                    if best_price is None or p.price < best_price:
                        best_price = p.price
                        best_name = name

        # Run decision engine
        try:
            _store_prov = getattr(result, "ebay_stores_provenance", None) or {}
            verdict = self._decision.evaluate(
                product=product,
                demand=demand,
                supplier_price=best_price,
                # C11 — the real store count, as an ADVISORY row. Reported,
                # never gated: there is no competitor threshold in config, and
                # a short or widened store search is a floor, not a total.
                competitor_store_count=_store_prov.get("store_count"),
                competitor_stores_verified=(
                    _store_prov.get("provenance") == "verified"
                ),
            )
            result.verdict = {
                "verdict": verdict.verdict,
                "profit": verdict.profit,
                "margin": verdict.margin,
                "filters": [
                    {
                        "name": f.name,
                        "passed": f.passed,
                        "actual": f.actual,
                        "expected": f.expected,
                        "verified": f.verified,
                        # Without this a JSON consumer cannot tell an
                        # information row from a rule that decided the verdict.
                        "advisory": f.advisory,
                    }
                    for f in verdict.filters
                ],
            }
        except Exception as e:
            logger.exception("Decision engine failed")
            result.errors.append(f"Decision engine failed: {e}")
            result.verdict = {"verdict": "error", "profit": 0, "margin": 0, "filters": []}

        # Calculate profit breakdown
        if best_price is not None:
            try:
                result.profit = calculate_profit(product.price, best_price)
            except Exception as e:
                logger.exception("Profit calc failed")
                result.errors.append(f"Profit calc failed: {e}")
                result.profit = {}
        else:
            result.profit = {}

        return best_price, best_name

    # ================================================================
    # Step 6 — Database
    # ================================================================

    def _save_to_db(
        self,
        product,
        demand,
        supplier_products: dict[str, list],
        analysis,
        result: PipelineResult,
    ):
        """Persist all pipeline results to PostgreSQL."""
        db = SessionLocal()
        try:
            product_id = save_product(db, product)
            result.db_product_id = product_id

            # Demand
            if demand and demand.verified:
                save_demand_data(db, product_id, demand)

            # Supplier matches
            for name, products in supplier_products.items():
                for p in products[:5]:
                    if p.price <= 0:
                        continue
                    save_supplier_match_data(db, product_id, {
                        "supplier_name": name,
                        "supplier_url": p.url,
                        "supplier_title": p.title,
                        "supplier_price": p.price,
                        "delivery_days_min": p.delivery_days_min,
                        "delivery_days_max": p.delivery_days_max,
                        "verified": p.verified,
                    })

            # LLM analysis
            if result.analysis:
                save_analysis_data(db, product_id, {
                    "brand_verdict": analysis.brand_verdict,
                    "brand_reasoning": analysis.brand_reasoning,
                    "demand_assessment": analysis.demand_assessment,
                    "demand_reasoning": analysis.demand_reasoning,
                    "supplier_match_notes": (
                        analysis.best_supplier_match.reasoning
                        if analysis.best_supplier_match else None
                    ),
                    "llm_raw_response": analysis.raw_response,
                })

            # Verdict
            if result.verdict:
                save_verdict_data(db, product_id, {
                    "verdict": result.verdict.get("verdict", "pending"),
                    "profit_amount": result.verdict.get("profit", 0),
                    "profit_margin": result.verdict.get("margin", 0),
                    "filter_results": result.verdict.get("filters", []),
                    "scorecard": result.scorecard,
                })

            logger.info("Saved product %d to database", product_id)

        except Exception as e:
            logger.exception("Database save failed")
            result.errors.append(f"DB save failed: {e}")
        finally:
            db.close()

    # ================================================================
    # Step 7 — Scorecard
    # ================================================================

    def _build_scorecard(
        self,
        product,
        demand,
        analysis,
        result: PipelineResult,
    ) -> str:
        """Human-readable scorecard for terminal display."""
        lines = []
        v = result.verdict.get("verdict", "?").upper()
        lines.append(f"VERDICT: {v}")
        lines.append("")

        # Product
        lines.append(f"Product: {product.title[:70]}")
        lines.append(f"eBay Price: GBP {product.price:.2f}")
        lines.append("")

        # Demand. Two kinds of evidence under two headings: a sale is demand, a
        # live listing is supply. Merged under one "DEMAND" heading the reader
        # cannot tell which is which, which is how a listing price came to be
        # printed as an "Avg sold".
        if demand and demand.verified:
            lines.append("DEMAND")
            if demand.sold_count_30d is not None:
                lines.append(f"  30-day sold: {demand.sold_count_30d}")
            if demand.sold_count_7d is not None:
                lines.append(f"  7-day sold:  {demand.sold_count_7d}")
            if demand.avg_sold_price is not None:
                lines.append(f"  Avg sold:    GBP {demand.avg_sold_price:.2f}")
        else:
            lines.append("DEMAND: unverified")
        if demand and demand.active_listings_in_band is not None:
            lines.append("LIVE LISTINGS (supply, not sales)")
            lines.append(f"  In band:     {demand.active_listings_in_band}")
            if demand.avg_active_price is not None:
                lines.append(f"  Avg asking:  GBP {demand.avg_active_price:.2f}")
        lines.append("")

        # LLM
        lines.append("ANALYSIS")
        lines.append(f"  Brand:  {analysis.brand_verdict} ({analysis.brand_reasoning[:60]})")
        lines.append(f"  Demand: {analysis.demand_assessment} ({analysis.demand_reasoning[:60]})")
        lines.append(f"  Action: {analysis.recommended_action}")
        if analysis.risk_flags:
            lines.append(f"  Risks:  {', '.join(analysis.risk_flags)}")
        lines.append("")

        # Filters
        lines.append("FILTERS")
        for f in result.verdict.get("filters", []):
            tick = "PASS" if f["passed"] else "FAIL"
            v_ = "verified" if f.get("verified") else "unverified"
            lines.append(f"  [{tick}] {f['name']}: {f['actual']} (expect {f['expected']}) [{v_}]")
        lines.append("")

        # Profit
        p = result.profit
        if p:
            lines.append("PROFIT")
            lines.append(f"  Supplier:     GBP {p.get('supplier_price', 0):.2f}")
            lines.append(f"  eBay fee:     GBP {p.get('ebay_fee', 0):.2f}")
            lines.append(f"  Returns buf:  GBP {p.get('returns_buffer', 0):.2f}")
            lines.append(f"  Net profit:   GBP {p.get('profit', 0):.2f}")
            lines.append(f"  Margin:       {p.get('margin', 0):.1f}%")
        lines.append("")

        # Errors
        if result.errors:
            lines.append("ERRORS")
            for e in result.errors:
                lines.append(f"  - {e}")

        return "\n".join(lines)

    async def close(self):
        """Clean up all scrapers and the LLM client."""
        await self._analyzer.close()
        for scraper in self._supplier_instances.values():
            await scraper.close()
        self._ebay.close()
