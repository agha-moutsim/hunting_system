"""
eBay Hunter — Streamlit Dashboard

Product sourcing analysis: scrape eBay, find suppliers, run LLM analysis, show verdicts.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import DATABASE_URL, FILTERS, OLLAMA_BASE_URL, OLLAMA_MODEL, EBAY_CLIENT_ID
from db.database import SessionLocal
from db.queries import (
    get_recent_products,
    get_product_by_url,
    save_product,
    save_demand_data,
    save_supplier_match_data,
    save_analysis_data,
    save_verdict_data,
)
from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict
from engine.decisions import DecisionEngine, Verdict as VerdictData
from engine.scorecard import format_scorecard
from llm.analyzer import ProductAnalyzer, LLMAnalysis
from scrapers.ebay import EbayScraper
from scrapers.base import ScrapedProduct, DemandData as DemandDataDTO
from utils.filters import load_filters, save_filters, reset_filters, save_preset, load_preset, list_presets, delete_preset, get_defaults

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Page Config ────────────────────────────────────────────────
st.set_page_config(
    page_title="eBay Hunter",
    page_icon="🎯",
    layout="wide",
)

# ─── Async Helper ────────────────────────────────────────────────

def _run_async(coro):
    """Run an async coroutine from synchronous Streamlit code."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── Status Checks ──────────────────────────────────────────────

@st.cache_resource(ttl=60)
def check_db_status() -> bool:
    """Ping the database to verify connectivity."""
    try:
        db: Session = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


@st.cache_resource(ttl=120)
def check_ollama_status() -> bool:
    """Ping the Ollama /api/tags endpoint."""
    import httpx

    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


# ─── Database Session (cached) ──────────────────────────────────

@st.cache_resource
def get_db_session():
    """Return a cached SQLAlchemy session factory."""
    return SessionLocal


# ─── Supplier Search ────────────────────────────────────────────

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
        try:
            scraper = ScraperClass()
            try:
                results = await scraper.search(query)
            finally:
                await scraper.close()
            return name, results
        except Exception as e:
            logger.warning("Supplier search failed for %s: %s", name, e)
            return name, []

    pairs = await asyncio.gather(*(_run_one(name, cls) for name, cls in scrapers))

    all_results: list[ScrapedProduct] = []
    for name, results in pairs:
        icon = "✓" if results else "–"
        if progress:
            progress(f"{icon} {name}: {len(results)} product(s)")
        all_results.extend(results)

    all_results.sort(key=lambda p: p.price)
    return all_results


# ─── Full Analysis Pipeline ─────────────────────────────────────

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
        # Step 1: Get eBay product
        _report("Step 1/5 — Searching eBay…")
        if is_url:
            ebay_product = ebay.get_details(query)
        else:
            search_results = ebay.search(query, limit=5)
            if not search_results:
                results["errors"].append(
                    "eBay requires API keys to search. "
                    "Get free keys at https://developer.ebay.com and add them to .env"
                )
                return results
            ebay_product = search_results[0]

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

        # Step 3: Search suppliers
        _report("Step 3/5 — Searching 7 suppliers in parallel (slowest step, ~1–2 min)…")
        supplier_results = await search_all_suppliers(ebay_product.title, progress=_report)
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
        llm_result = await analyzer.analyze(product_dict, demand_dict, supplier_dicts)
        results["llm_analysis"] = llm_result
        await analyzer.close()
        if llm_result:
            _report(f"✓ AI verdict: {llm_result.brand_verdict} brand, {llm_result.demand_assessment} demand → {llm_result.recommended_action}")
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


def _save_to_db(results: dict):
    """Persist analysis results to PostgreSQL."""
    db: Session = SessionLocal()
    try:
        ebay_product: ScrapedProduct = results["ebay_product"]
        demand: DemandDataDTO = results["demand"]
        suppliers: list[ScrapedProduct] = results["supplier_matches"]
        llm: Optional[LLMAnalysis] = results["llm_analysis"]
        verdict: Optional[VerdictData] = results["verdict"]

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


# ─── Custom Filters ──────────────────────────────────────────────

def get_active_filters() -> dict:
    """Return current active filters (from session state, or load from disk)."""
    if "custom_filters" not in st.session_state:
        st.session_state["custom_filters"] = load_filters()
    return st.session_state["custom_filters"]


def set_active_filters(filters: dict):
    """Update filters in session state and persist to disk."""
    st.session_state["custom_filters"] = filters
    save_filters(filters)


# ─── UI: Sidebar ────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.title("🎯 eBay Hunter")
        st.caption("Product Sourcing Intelligence")

        st.divider()

        # DB status
        db_ok = check_db_status()
        if db_ok:
            st.success("Database: Connected")
        else:
            st.error("Database: Disconnected")

        # Ollama status
        ollama_ok = check_ollama_status()
        if ollama_ok:
            st.success(f"Ollama: Online ({OLLAMA_MODEL})")
        else:
            st.warning("Ollama: Offline (LLM analysis disabled)")

        # eBay API status
        if not EBAY_CLIENT_ID:
            st.warning(
                "eBay API keys missing. "
                "[Get free keys](https://developer.ebay.com) and add to .env"
            )
        else:
            st.success("eBay API: Configured")

        st.divider()

        # ── Custom Filters Editor ────────────────────────────────
        st.divider()
        custom_filters = get_active_filters()

        with st.expander("Filter Settings", expanded=False):
            st.caption("Adjust filters to match your sourcing criteria")

            c1, c2 = st.columns(2)
            with c1:
                price_min = st.number_input(
                    "Min price (£)", min_value=0.0, max_value=100.0,
                    value=float(custom_filters["price_min"]), step=0.50, key="f_price_min",
                )
                demand_30d = st.number_input(
                    "Min sold (30d)", min_value=0, max_value=500,
                    value=int(custom_filters["demand_min_30d"]), step=1, key="f_demand_30d",
                )
            with c2:
                price_max = st.number_input(
                    "Max price (£)", min_value=0.0, max_value=500.0,
                    value=float(custom_filters["price_max"]), step=0.50, key="f_price_max",
                )
                demand_7d = st.number_input(
                    "Min sold (7d)", min_value=0, max_value=100,
                    value=int(custom_filters["demand_min_7d"]), step=1, key="f_demand_7d",
                )

            delivery_max = st.slider(
                "Max delivery days", min_value=1, max_value=60,
                value=int(custom_filters["delivery_target_max"]), key="f_delivery",
            )

            btn_col1, btn_col2, btn_col3 = st.columns(3)
            with btn_col1:
                if st.button("Apply", use_container_width=True, type="primary"):
                    new_filters = {
                        "price_min": price_min,
                        "price_max": price_max,
                        "demand_min_30d": demand_30d,
                        "demand_min_7d": demand_7d,
                        "demand_strong_30d": custom_filters.get("demand_strong_30d", 30),
                        "delivery_target_max": delivery_max,
                    }
                    set_active_filters(new_filters)
                    st.success("Filters updated!")
                    st.rerun()
            with btn_col2:
                if st.button("Reset", use_container_width=True):
                    reset_filters()
                    st.session_state.pop("custom_filters", None)
                    st.rerun()
            with btn_col3:
                preset_name = st.text_input("Preset name", key="preset_name_input", label_visibility="collapsed", placeholder="Save as...")
                if preset_name and st.button("Save", use_container_width=True):
                    save_preset(preset_name, custom_filters)
                    st.success(f"Saved: {preset_name}")
                    st.rerun()

            # Load/delete presets
            presets = list_presets()
            if presets:
                with st.expander("Load a preset", expanded=False):
                    selected = st.selectbox("Presets", presets, key="preset_select", label_visibility="collapsed")
                    lcol1, lcol2 = st.columns(2)
                    with lcol1:
                        if st.button("Load", use_container_width=True):
                            loaded = load_preset(selected)
                            if loaded:
                                set_active_filters(loaded)
                                st.rerun()
                    with lcol2:
                        if st.button("Delete", use_container_width=True):
                            delete_preset(selected)
                            st.rerun()

        # Show current active filters compactly
        f = get_active_filters()
        st.caption(
            f"Filters: £{f['price_min']:.0f}–£{f['price_max']:.0f} | "
            f"30d≥{f['demand_min_30d']} | 7d≥{f['demand_min_7d']} | "
            f"delivery≤{f['delivery_target_max']}d"
        )

        st.divider()
        st.caption(f"DB: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'local'}")


# ─── UI: Analyze Tab ────────────────────────────────────────────

def render_analyze_tab():
    st.header("Analyze Product")

    col1, col2 = st.columns([3, 1])
    with col1:
        query_input = st.text_input(
            "eBay URL or search query",
            placeholder="e.g. https://www.ebay.co.uk/itm/... or wireless earbuds",
        )
    with col2:
        analyze_btn = st.button("Analyze Product", type="primary", use_container_width=True)

    if analyze_btn and query_input:
        is_url = "ebay" in query_input.lower() and ("/itm/" in query_input or "/sch/" in query_input)

        status_box = st.status("Starting analysis…", expanded=True)

        def _progress(msg: str):
            status_box.write(msg)

        try:
            with status_box:
                custom_filters = get_active_filters()
                results = _run_async(run_analysis_pipeline(
                    query_input, is_url=is_url, progress=_progress, filters=custom_filters
                ))
                if results.get("errors"):
                    status_box.update(label="Analysis finished with warnings", state="error", expanded=True)
                else:
                    status_box.update(label="Analysis complete", state="complete", expanded=False)
        except Exception as e:
            status_box.update(label="Analysis failed", state="error", expanded=True)
            st.error(str(e))
            return

        if results["errors"]:
            for err in results["errors"]:
                st.error(err)
            return

        if not results["ebay_product"]:
            st.error("No product data returned.")
            return

        # Save to DB
        try:
            _save_to_db(results)
        except Exception as e:
            st.warning(f"Analysis complete but DB save failed: {e}")

        # ── Display Results ──
        ebay_product: ScrapedProduct = results["ebay_product"]
        demand: Optional[DemandDataDTO] = results["demand"]
        suppliers: list[ScrapedProduct] = results["supplier_matches"]
        llm: Optional[LLMAnalysis] = results["llm_analysis"]
        verdict: Optional[VerdictData] = results["verdict"]

        # Product header
        st.divider()
        img_col, info_col = st.columns([1, 2])
        with img_col:
            if ebay_product.image_url:
                st.image(ebay_product.image_url, width=300)
        with info_col:
            st.subheader(ebay_product.title)
            st.markdown(f"**Price:** £{ebay_product.price:.2f}")
            st.markdown(f"**Condition:** {ebay_product.condition}")
            if ebay_product.seller:
                st.markdown(f"**Seller:** {ebay_product.seller}")
            st.link_button("View on eBay", ebay_product.url, type="secondary")

        # Price comparison table
        st.subheader("Price Comparison")
        comp_cols = st.columns(len(suppliers[:4]) + 1 if suppliers else 1)
        with comp_cols[0]:
            st.metric("eBay Price", f"£{ebay_product.price:.2f}")
        for i, s in enumerate(suppliers[:4]):
            with comp_cols[i + 1]:
                st.metric(
                    s.source,
                    f"£{s.price:.2f}",
                    delta=f"£{ebay_product.price - s.price:.2f} profit",
                    delta_color="normal",
                )

        if not suppliers:
            st.info("No supplier matches found.")

        # Demand metrics
        st.subheader("Demand Metrics")
        if demand and demand.sold_count_30d is not None:
            d_cols = st.columns(4)
            with d_cols[0]:
                st.metric("Sold (30d)", demand.sold_count_30d or 0)
            with d_cols[1]:
                st.metric("Sold (7d)", demand.sold_count_7d or 0)
            with d_cols[2]:
                st.metric("Avg Sold Price", f"£{demand.avg_sold_price:.2f}" if demand.avg_sold_price else "N/A")
            with d_cols[3]:
                price_range = ""
                if demand.lowest_sold_price is not None and demand.highest_sold_price is not None:
                    price_range = f"£{demand.lowest_sold_price:.2f} – £{demand.highest_sold_price:.2f}"
                st.metric("Price Range", price_range or "N/A")
        else:
            st.info("No demand data available.")

        # LLM Analysis
        if llm:
            st.subheader("LLM Analysis")
            llm_cols = st.columns(2)
            with llm_cols[0]:
                brand_color = {"generic": "green", "branded": "red", "ambiguous": "orange"}.get(
                    llm.brand_verdict, "gray"
                )
                st.markdown(f"**Brand:** :{brand_color}[{llm.brand_verdict}]")
                if llm.brand_reasoning:
                    st.caption(llm.brand_reasoning)

                demand_color = {"strong": "green", "moderate": "orange", "weak": "red", "spike": "blue"}.get(
                    llm.demand_assessment, "gray"
                )
                st.markdown(f"**Demand:** :{demand_color}[{llm.demand_assessment}]")
                if llm.demand_reasoning:
                    st.caption(llm.demand_reasoning)

            with llm_cols[1]:
                action_color = {"source": "green", "skip": "red", "investigate": "orange"}.get(
                    llm.recommended_action, "gray"
                )
                st.markdown(f"**Action:** :{action_color}[{llm.recommended_action}]")
                st.markdown(f"**Supplier type:** {llm.supplier_type}")

                if llm.risk_flags:
                    st.markdown("**Risk flags:**")
                    for flag in llm.risk_flags:
                        st.warning(flag)

            with st.expander("Raw LLM Response"):
                st.code(llm.raw_response, language="json")

        # Profit & Verdict
        if verdict:
            st.subheader("Profit & Verdict")

            v_cols = st.columns(3)
            with v_cols[0]:
                if verdict.profit > 0:
                    st.success(f"Profit: £{verdict.profit:.2f}")
                else:
                    st.error(f"Profit: £{verdict.profit:.2f}")
            with v_cols[1]:
                st.metric("Margin", f"{verdict.margin:.1f}%")
            with v_cols[2]:
                v = verdict.verdict.lower()
                if v == "pass":
                    st.success("VERDICT: PASS")
                elif v == "fail":
                    st.error("VERDICT: FAIL")
                else:
                    st.warning("VERDICT: PENDING")

            # Filter breakdown
            with st.expander("Filter Details", expanded=True):
                for f in verdict.filters:
                    icon = "PASS" if f.passed else "FAIL"
                    color = "green" if f.passed else "red"
                    st.markdown(
                        f":{color}[{icon}] **{f.name}**: {f.actual} (expected {f.expected})"
                    )

        # Scorecard
        if results["scorecard"]:
            with st.expander("Full Scorecard", expanded=False):
                st.code(results["scorecard"], language=None)


# ─── UI: History Tab ────────────────────────────────────────────

def render_history_tab():
    st.header("Analysis History")

    db: Session = SessionLocal()

    # Verdict filter
    filter_col1, filter_col2 = st.columns([1, 3])
    with filter_col1:
        verdict_filter = st.selectbox(
            "Filter by verdict",
            ["All", "pass", "fail", "pending"],
            index=0,
        )

    try:
        products = get_recent_products(db, limit=50)

        if verdict_filter != "All":
            products = [p for p in products if p.get("verdict") == verdict_filter]

        if not products:
            st.info("No products found. Run an analysis first.")
            return

        st.caption(f"Showing {len(products)} products")

        for p in products:
            verdict_str = p.get("verdict") or "pending"
            v_color = {"pass": "green", "fail": "red"}.get(verdict_str, "orange")

            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

                with col1:
                    title = p.get("title", "Unknown")
                    if len(title) > 60:
                        title = title[:57] + "..."
                    st.markdown(f"**{title}**")

                with col2:
                    price = p.get("price")
                    st.markdown(f"£{price:.2f}" if price else "N/A")

                with col3:
                    profit = p.get("profit")
                    if profit is not None:
                        st.markdown(f"£{profit:.2f}")
                    else:
                        st.markdown("—")

                with col4:
                    st.markdown(f":{v_color}[{verdict_str.upper()}]")

                # Clickable row
                if st.button("View Details", key=f"view_{p['id']}", use_container_width=True):
                    st.session_state["selected_product_id"] = p["id"]
                    st.rerun()

    except Exception as e:
        st.error(f"Failed to load history: {e}")
    finally:
        db.close()


# ─── UI: Product Detail View ────────────────────────────────────

def render_product_detail(product_id: int):
    db: Session = SessionLocal()

    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            st.error("Product not found.")
            return

        demand = db.query(DemandData).filter(DemandData.product_id == product_id).first()
        suppliers = db.query(SupplierMatch).filter(SupplierMatch.product_id == product_id).all()
        analysis = db.query(Analysis).filter(Analysis.product_id == product_id).first()
        verdict = db.query(Verdict).filter(Verdict.product_id == product_id).first()

        # Back button
        if st.button("← Back to History"):
            del st.session_state["selected_product_id"]
            st.rerun()

        st.divider()

        # Product header
        img_col, info_col = st.columns([1, 2])
        with img_col:
            if product.image_url:
                st.image(product.image_url, width=300)
        with info_col:
            st.subheader(product.title)
            st.markdown(f"**Price:** £{product.price:.2f}")
            st.markdown(f"**Condition:** {product.condition}")
            if product.seller:
                st.markdown(f"**Seller:** {product.seller}")
            if product.ebay_url:
                st.link_button("View on eBay", product.ebay_url, type="secondary")

        # Price comparison
        st.subheader("Price Comparison")
        if suppliers:
            comp_cols = st.columns(len(suppliers[:4]) + 1)
            with comp_cols[0]:
                st.metric("eBay Price", f"£{product.price:.2f}")
            for i, s in enumerate(suppliers[:4]):
                with comp_cols[i + 1]:
                    st.metric(
                        s.supplier_name,
                        f"£{s.supplier_price:.2f}",
                        delta=f"£{product.price - s.supplier_price:.2f}" if product.price else None,
                    )
        else:
            st.info("No supplier data recorded.")

        # Demand
        st.subheader("Demand Metrics")
        if demand:
            d_cols = st.columns(4)
            with d_cols[0]:
                st.metric("Sold (30d)", demand.sold_count_30d or 0)
            with d_cols[1]:
                st.metric("Sold (7d)", demand.sold_count_7d or 0)
            with d_cols[2]:
                st.metric("Avg Sold", f"£{demand.avg_sold_price:.2f}" if demand.avg_sold_price else "N/A")
            with d_cols[3]:
                st.metric("Data Source", demand.data_source or "N/A")
        else:
            st.info("No demand data recorded.")

        # LLM Analysis
        if analysis:
            st.subheader("LLM Analysis")
            a_cols = st.columns(2)
            with a_cols[0]:
                brand_color = {"generic": "green", "branded": "red"}.get(analysis.brand_verdict, "orange")
                st.markdown(f"**Brand:** :{brand_color}[{analysis.brand_verdict}]")
                if analysis.brand_reasoning:
                    st.caption(analysis.brand_reasoning)

                demand_color = {"strong": "green", "moderate": "orange", "weak": "red"}.get(
                    analysis.demand_assessment, "blue"
                )
                st.markdown(f"**Demand:** :{demand_color}[{analysis.demand_assessment}]")
                if analysis.demand_reasoning:
                    st.caption(analysis.demand_reasoning)

            with a_cols[1]:
                if analysis.supplier_match_notes:
                    st.markdown("**Supplier notes:**")
                    st.caption(analysis.supplier_match_notes)

            if analysis.llm_raw_response:
                with st.expander("Raw LLM Response"):
                    st.code(analysis.llm_raw_response, language="json")

        # Verdict
        if verdict:
            st.subheader("Verdict")

            v_cols = st.columns(3)
            with v_cols[0]:
                v = verdict.verdict.lower()
                if v == "pass":
                    st.success(f"VERDICT: PASS")
                elif v == "fail":
                    st.error(f"VERDICT: FAIL")
                else:
                    st.warning(f"VERDICT: PENDING")
            with v_cols[1]:
                st.metric("Profit", f"£{verdict.profit_amount:.2f}" if verdict.profit_amount else "N/A")
            with v_cols[2]:
                st.metric("Margin", f"{verdict.profit_margin:.1f}%" if verdict.profit_margin else "N/A")

            # Filter breakdown
            if verdict.filter_results:
                with st.expander("Filter Details", expanded=True):
                    for f in verdict.filter_results:
                        if isinstance(f, dict):
                            passed = f.get("passed", False)
                            name = f.get("name", "Unknown")
                            actual = f.get("actual", "")
                            expected = f.get("expected", "")
                        else:
                            passed = getattr(f, "passed", False)
                            name = getattr(f, "name", "Unknown")
                            actual = getattr(f, "actual", "")
                            expected = getattr(f, "expected", "")

                        icon = "PASS" if passed else "FAIL"
                        color = "green" if passed else "red"
                        st.markdown(f":{color}[{icon}] **{name}**: {actual} (expected {expected})")

            # Scorecard
            if verdict.scorecard:
                with st.expander("Full Scorecard"):
                    st.code(verdict.scorecard, language=None)

        # Timestamps
        st.divider()
        st.caption(f"Created: {product.created_at}")
        st.caption(f"Updated: {product.updated_at}")

    except Exception as e:
        st.error(f"Error loading product: {e}")
    finally:
        db.close()


# ─── Main ───────────────────────────────────────────────────────

def main():
    render_sidebar()

    # Check if we're viewing a product detail
    if "selected_product_id" in st.session_state:
        render_product_detail(st.session_state["selected_product_id"])
        return

    # Main tabs
    tab_analyze, tab_history = st.tabs(["Analyze", "History"])

    with tab_analyze:
        render_analyze_tab()

    with tab_history:
        render_history_tab()


if __name__ == "__main__":
    main()
