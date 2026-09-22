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
from utils.theme import apply_theme
from deep_search import deep_search_product, DeepSearchResult

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
        st.markdown("""
        <div style="text-align: center; padding: 0.5rem 0 1rem 0;">
            <div style="
                width: 48px; height: 48px; border-radius: 14px;
                background: linear-gradient(135deg, #3B82F6, #2563EB);
                display: inline-flex; align-items: center; justify-content: center;
                font-size: 1.5rem; color: white;
                box-shadow: 0 4px 12px rgba(59,130,246,0.3);
                margin-bottom: 8px;
            ">🎯</div>
            <h1 style="color: #F8FAFC; font-size: 1.3rem; font-weight: 700;
                       letter-spacing: -0.02em; margin: 0;">eBay Hunter</h1>
            <p style="color: #94A3B8; font-size: 0.75rem; margin: 0;">Product Sourcing Intelligence</p>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # Status indicators
        st.markdown('<p style="color:#64748B;font-size:0.7rem;text-transform:uppercase;letter-spacing:0.05em;font-weight:600;margin-bottom:0.5rem;">System Status</p>', unsafe_allow_html=True)

        # DB status
        db_ok = check_db_status()
        if db_ok:
            st.markdown('<span style="color:#10B981;font-size:0.85rem;">● Database: Connected</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:#EF4444;font-size:0.85rem;">● Database: Disconnected</span>', unsafe_allow_html=True)

        # Ollama status
        ollama_ok = check_ollama_status()
        if ollama_ok:
            st.markdown(f'<span style="color:#10B981;font-size:0.85rem;">● Ollama: Online ({OLLAMA_MODEL})</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:#F59E0B;font-size:0.85rem;">● Ollama: Offline</span>', unsafe_allow_html=True)

        # eBay API status
        if not EBAY_CLIENT_ID:
            st.markdown(
                '<span style="color:#F59E0B;font-size:0.85rem;">● eBay API: Missing keys</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<span style="color:#10B981;font-size:0.85rem;">● eBay API: Configured</span>',
                unsafe_allow_html=True,
            )

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

            margin_min = st.slider(
                "Min margin %", min_value=0, max_value=50,
                value=int(custom_filters.get("margin_min", 25)), key="f_margin",
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
                        "delivery_min": custom_filters.get("delivery_min", 3),
                        "delivery_target_max": delivery_max,
                        "delivery_exception_max": custom_filters.get("delivery_exception_max", 25),
                        "margin_min": float(margin_min),
                        "brand_filter": custom_filters.get("brand_filter", "generic_only"),
                        "condition": custom_filters.get("condition", "New"),
                        "buy_it_now": custom_filters.get("buy_it_now", True),
                        "uk_only": custom_filters.get("uk_only", True),
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
            f"Filters: £{f['price_min']:.0f}-£{f['price_max']:.0f} | "
            f"30d>={f['demand_min_30d']} | 7d>={f['demand_min_7d']} | "
            f"delivery<={f['delivery_target_max']}d | "
            f"margin>={f.get('margin_min', 25)}%"
        )

        st.divider()
        st.caption(f"DB: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'local'}")


# ─── UI: Analyze Tab ────────────────────────────────────────────

def render_analyze_tab():
    # Modern input card
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 1.5rem 2rem;
        margin-bottom: 1rem;
    ">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 0.8rem;">
            <div style="
                width: 36px; height: 36px; border-radius: 10px;
                background: linear-gradient(135deg, #3B82F6, #2563EB);
                display: flex; align-items: center; justify-content: center;
                font-size: 1.1rem; color: white;
            ">🔍</div>
            <div>
                <h3 style="color: #F8FAFC; font-size: 1.1rem; font-weight: 600; margin: 0;">
                    Analyze Product
                </h3>
                <p style="color: #94A3B8; font-size: 0.8rem; margin: 0;">
                    Enter an eBay URL or search query to start a full sourcing analysis
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([4, 1])
    with col1:
        query_input = st.text_input(
            "Search",
            placeholder="Paste an eBay UK product URL or type a search query (e.g. wireless earbuds, phone case)",
            label_visibility="collapsed",
        )
    with col2:
        analyze_btn = st.button("Analyze", type="primary", use_container_width=True)

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

        # ── Product Hero Card ──
        st.markdown("---")
        img_col, info_col = st.columns([1, 2])
        with img_col:
            if ebay_product.image_url:
                st.image(ebay_product.image_url, width=300)
        with info_col:
            st.markdown(f"### {ebay_product.title}")
            price_cols = st.columns(3)
            with price_cols[0]:
                st.metric("Listed Price", f"£{ebay_product.price:.2f}")
            with price_cols[1]:
                st.metric("Condition", ebay_product.condition)
            with price_cols[2]:
                if ebay_product.seller:
                    st.metric("Seller", ebay_product.seller)
            st.link_button("View on eBay →", ebay_product.url, type="secondary")

        # ── Price Comparison ──
        if suppliers:
            st.markdown("---")
            st.markdown("#### 💰 Price Comparison")
            comp_cols = st.columns(len(suppliers[:5]) + 1)
            with comp_cols[0]:
                st.metric("eBay Price", f"£{ebay_product.price:.2f}")
            for i, s in enumerate(suppliers[:5]):
                with comp_cols[i + 1]:
                    profit = ebay_product.price - s.price
                    st.metric(
                        s.source,
                        f"£{s.price:.2f}",
                        delta=f"+£{profit:.2f}" if profit > 0 else f"£{profit:.2f}",
                        delta_color="normal",
                    )

        # ── Demand Metrics ──
        st.markdown("---")
        st.markdown("#### 📊 Demand Metrics")
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

        # ── LLM Analysis ──
        if llm:
            st.markdown("---")
            st.markdown("#### 🤖 AI Analysis")

            llm_card1, llm_card2 = st.columns(2)
            with llm_card1:
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

            with llm_card2:
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

        # ── Profit & Verdict ──
        if verdict:
            st.markdown("---")
            st.markdown("#### ✅ Verdict")

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
                    icon = "✅" if f.passed else "❌"
                    st.markdown(
                        f"{icon} **{f.name}**: {f.actual} (expected {f.expected})"
                    )

        # Scorecard
        if results["scorecard"]:
            with st.expander("Full Scorecard", expanded=False):
                st.code(results["scorecard"], language=None)


# ─── UI: History Tab ────────────────────────────────────────────

def render_history_tab():
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 1.5rem 2rem;
        margin-bottom: 1rem;
    ">
        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="
                width: 36px; height: 36px; border-radius: 10px;
                background: linear-gradient(135deg, #8B5CF6, #7C3AED);
                display: flex; align-items: center; justify-content: center;
                font-size: 1.1rem; color: white;
            ">📋</div>
            <div>
                <h3 style="color: #F8FAFC; font-size: 1.1rem; font-weight: 600; margin: 0;">
                    Analysis History
                </h3>
                <p style="color: #94A3B8; font-size: 0.8rem; margin: 0;">
                    Browse past analyses and track product performance
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    db: Session = SessionLocal()

    # Filter bar
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
    with filter_col1:
        verdict_filter = st.selectbox(
            "Verdict",
            ["All", "pass", "fail", "pending"],
            index=0,
            label_visibility="collapsed",
        )

    try:
        products = get_recent_products(db, limit=50)

        if verdict_filter != "All":
            products = [p for p in products if p.get("verdict") == verdict_filter]

        if not products:
            st.info("No products found. Run an analysis first.")
            return

        st.caption(f"Showing {len(products)} product(s)")

        for p in products:
            verdict_str = p.get("verdict") or "pending"
            v_badge = {
                "pass": '<span style="background:#059669;color:white;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;">PASS</span>',
                "fail": '<span style="background:#DC2626;color:white;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;">FAIL</span>',
            }.get(verdict_str, '<span style="background:#D97706;color:white;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;">PENDING</span>')

            title = p.get("title", "Unknown")
            if len(title) > 65:
                title = title[:62] + "..."
            price = p.get("price")
            profit = p.get("profit")

            profit_html = ""
            if profit is not None:
                color = "#10B981" if profit >= 0 else "#EF4444"
                sign = "+" if profit >= 0 else ""
                profit_html = f'<span style="color:{color};font-weight:600;">{sign}£{profit:.2f}</span>'
            else:
                profit_html = '<span style="color:#64748B;">—</span>'

            st.markdown(f"""
            <div style="
                background: #1E293B;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 1rem 1.2rem;
                margin-bottom: 0.5rem;
                transition: border-color 0.2s;
                display: flex;
                align-items: center;
                justify-content: space-between;
            ">
                <div style="flex: 1; min-width: 0;">
                    <div style="color: #F8FAFC; font-weight: 500; font-size: 0.95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 500px;">
                        {title}
                    </div>
                    <div style="color: #94A3B8; font-size: 0.8rem; margin-top: 2px;">
                        £{price:.2f if price else '—'}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 16px; flex-shrink: 0;">
                    <div style="text-align: right; min-width: 80px;">
                        {profit_html}
                    </div>
                    {v_badge}
                </div>
            </div>
            """, unsafe_allow_html=True)

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

        st.markdown("---")

        # Product hero card
        img_col, info_col = st.columns([1, 2])
        with img_col:
            if product.image_url:
                st.image(product.image_url, width=300)
        with info_col:
            st.markdown(f"### {product.title}")
            price_cols = st.columns(3)
            with price_cols[0]:
                st.metric("Listed Price", f"£{product.price:.2f}")
            with price_cols[1]:
                st.metric("Condition", product.condition)
            with price_cols[2]:
                if product.seller:
                    st.metric("Seller", product.seller)
            if product.ebay_url:
                st.link_button("View on eBay →", product.ebay_url, type="secondary")

        # Price comparison
        st.markdown("---")
        st.markdown("#### 💰 Price Comparison")
        if suppliers:
            comp_cols = st.columns(len(suppliers[:5]) + 1)
            with comp_cols[0]:
                st.metric("eBay Price", f"£{product.price:.2f}")
            for i, s in enumerate(suppliers[:5]):
                with comp_cols[i + 1]:
                    st.metric(
                        s.supplier_name,
                        f"£{s.supplier_price:.2f}",
                        delta=f"£{product.price - s.supplier_price:.2f}" if product.price else None,
                    )
        else:
            st.info("No supplier data recorded.")

        # Demand
        st.markdown("---")
        st.markdown("#### 📊 Demand Metrics")
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
            st.markdown("---")
            st.markdown("#### 🤖 AI Analysis")
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
            st.markdown("---")
            st.markdown("#### ✅ Verdict")

            v_cols = st.columns(3)
            with v_cols[0]:
                v = verdict.verdict.lower()
                if v == "pass":
                    st.success("VERDICT: PASS")
                elif v == "fail":
                    st.error("VERDICT: FAIL")
                else:
                    st.warning("VERDICT: PENDING")
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

                        icon = "✅" if passed else "❌"
                        st.markdown(f"{icon} **{name}**: {actual} (expected {expected})")

            # Scorecard
            if verdict.scorecard:
                with st.expander("Full Scorecard"):
                    st.code(verdict.scorecard, language=None)

        # Timestamps
        st.markdown("---")
        st.caption(f"Created: {product.created_at}  ·  Updated: {product.updated_at}")

    except Exception as e:
        st.error(f"Error loading product: {e}")
    finally:
        db.close()


# ─── UI: Deep Search Tab ─────────────────────────────────────────

def render_deep_search_tab():
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #0B1120 0%, #1A2E1A 50%, #0F2B0F 100%);
        border: 1px solid #2D5A2D;
        border-radius: 16px;
        padding: 1.8rem 2.2rem;
        margin-bottom: 1.5rem;
        position: relative;
        overflow: hidden;
    ">
        <div style="position: absolute; top: 0; right: 0; width: 250px; height: 250px;
                    background: radial-gradient(circle, rgba(16,185,129,0.1) 0%, transparent 70%);
                    pointer-events: none;"></div>
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 6px;">
            <div style="
                width: 44px; height: 44px; border-radius: 12px;
                background: linear-gradient(135deg, #10B981 0%, #059669 100%);
                display: flex; align-items: center; justify-content: center;
                font-size: 1.4rem;
            ">🔬</div>
            <div>
                <h2 style="color: #F8FAFC; font-size: 1.5rem; font-weight: 700; margin: 0;
                           letter-spacing: -0.02em;">
                    Deep Product Research
                </h2>
                <p style="color: #94A3B8; font-size: 0.85rem; margin: 0;">
                    Web-powered market analysis — eBay stats, supplier pricing, competition data
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    query = st.text_input(
        "Product Name",
        placeholder="e.g. Sony WH-1000XM5 headphones, vintage LEGO set...",
        label_visibility="collapsed",
    )

    if st.button("🔬  Research", type="primary", use_container_width=True, disabled=not query.strip()):
        with st.status("Running deep research...", expanded=True) as status:
            st.write("🔍  Searching eBay UK, suppliers, and web sources...")
            try:
                result: DeepSearchResult = deep_search_product(query.strip())
                status.update(label="Research complete", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Research failed", state="error")
                st.error(f"Deep search failed: {e}")
                return

        # ── Product Overview Card ──
        comp_badge_map = {
            "low": ("#059669", "#022C22"),
            "medium": ("#D97706", "#451A03"),
            "high": ("#DC2626", "#450A0A"),
        }
        profit_badge_map = {
            "high": ("#059669", "#022C22"),
            "medium": ("#D97706", "#451A03"),
            "low": ("#DC2626", "#450A0A"),
        }
        comp_color, comp_bg = comp_badge_map.get(result.competition_level.lower(), ("#64748B", "#1E293B"))
        profit_color, profit_bg = profit_badge_map.get(result.profit_potential.lower(), ("#64748B", "#1E293B"))

        st.markdown(f"""
        <div style="
            background: #1E293B;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 1.2rem 1.5rem;
            margin-bottom: 1rem;
        ">
            <div style="color: #F8FAFC; font-size: 1.15rem; font-weight: 600; margin-bottom: 6px;">
                {result.product_name or query}
            </div>
            <div style="color: #94A3B8; font-size: 0.85rem; margin-bottom: 10px;">
                {result.product_category}
            </div>
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <span style="background:{comp_bg}; color:{comp_color}; padding: 4px 14px;
                             border-radius: 20px; font-size: 0.78rem; font-weight: 600;
                             border: 1px solid {comp_color}33;">
                    Competition: {result.competition_level.title() or "—"}
                </span>
                <span style="background:{profit_bg}; color:{profit_color}; padding: 4px 14px;
                             border-radius: 20px; font-size: 0.78rem; font-weight: 600;
                             border: 1px solid {profit_color}33;">
                    Profit Potential: {result.profit_potential.title() or "—"}
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Price Comparison (multiple suppliers) ──
        if result.suppliers:
            st.markdown("""
            <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                         border-bottom: 1px solid #334155; padding-bottom: 6px;">
                💰  Price Comparison
            </div>
            """, unsafe_allow_html=True)

            comp_cols = st.columns(len(result.suppliers[:5]) + 1)
            with comp_cols[0]:
                st.metric("eBay Avg Price", f"£{result.ebay_avg_price:.2f}")
            for i, s in enumerate(result.suppliers[:5]):
                with comp_cols[i + 1]:
                    sprice = s.get("price", 0) if isinstance(s.get("price"), (int, float)) else 0
                    profit = result.ebay_avg_price - sprice if sprice > 0 else 0
                    delivery_str = s.get("delivery_days", "?")
                    supplier_type = s.get("supplier_type", "")
                    type_icon = "🏪" if supplier_type == "retailer" else "📦"
                    st.metric(
                        f"{type_icon} {s.get('name', f'Supplier {i+1}')}",
                        f"£{sprice:.2f}",
                        delta=f"+£{profit:.2f} ({delivery_str})" if profit > 0 else f"£{profit:.2f} ({delivery_str})",
                        delta_color="normal",
                    )
                    # Show full details if available
                    if s.get("seller_rating"):
                        st.caption(f"Rating: {s['seller_rating']}")
                    if s.get("seller_orders"):
                        st.caption(f"Orders: {s['seller_orders']}")
                    if s.get("url"):
                        st.link_button("View →", s["url"], key=f"supplier_{i}")

        # ── Profit & Verdict ──
        if result.verdict:
            st.markdown("""
            <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                         border-bottom: 1px solid #334155; padding-bottom: 6px;">
                ✅  Verdict
            </div>
            """, unsafe_allow_html=True)

            v_cols = st.columns(3)
            with v_cols[0]:
                if result.profit > 0:
                    st.success(f"Profit: £{result.profit:.2f}")
                else:
                    st.error(f"Profit: £{result.profit:.2f}")
            with v_cols[1]:
                st.metric("Margin", f"{result.margin:.1f}%")
            with v_cols[2]:
                v = result.verdict.upper()
                if v == "PASS":
                    st.success("VERDICT: PASS")
                elif v == "FAIL":
                    st.error("VERDICT: FAIL")
                else:
                    st.warning("VERDICT: PENDING")

            if result.filters_passed:
                with st.expander("Filter Details", expanded=True):
                    for f in result.filters_passed:
                        icon = "✅" if f.get("passed") else "❌"
                        verified = f.get("verified", False)
                        verify_tag = "" if verified else " ⚠️ Unverified"
                        st.markdown(f"{icon} **{f.get('name', '')}**: {f.get('actual', '')} (expected {f.get('expected', '')}){verify_tag}")

        # ── eBay Market Data ──
        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📊  eBay Market Data
        </div>
        """, unsafe_allow_html=True)

        # Check if we have real sold data
        has_real_data = result.ebay_total_sold_30d > 0

        if has_real_data:
            # Real sold data
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Sold (30d)", f"{result.ebay_total_sold_30d} items")
            m2.metric("Sold (7d)", f"{result.ebay_total_sold_7d} items")
            m3.metric("Price Range", f"£{result.ebay_price_min:.2f} - £{result.ebay_price_max:.2f}")
            m4.metric("Average Price", f"£{result.ebay_avg_price:.2f}")
        else:
            # LLM estimates
            m1, m2, m3 = st.columns(3)
            m1.metric("Est. Monthly Sold", f"{result.ebay_items_sold_month} ⚠️" if result.ebay_items_sold_month else "—")
            m2.metric("Price Range", f"{result.ebay_price_range} ⚠️" if result.ebay_price_range else "—")

            avg_price = "—"
            if result.ebay_price_range and "avg" in result.ebay_price_range.lower():
                import re as _re
                avg_match = _re.search(r"avg\s*£?([\d,.]+)", result.ebay_price_range, _re.IGNORECASE)
                if avg_match:
                    avg_price = f"£{avg_match.group(1)}"
            m3.metric("Average Price", avg_price)

        if result.ebay_top_sellers:
            st.markdown("**Top Sellers:**")
            for seller in result.ebay_top_sellers[:5]:
                s_name = seller.get("name", "Unknown")
                s_price = seller.get("avg_price", seller.get("price", "—"))
                s_url = seller.get("url", "")
                s_count = seller.get("sold_count", "")
                cols = st.columns([3, 1, 1, 1])
                cols[0].markdown(f"**{s_name}**")
                cols[1].markdown(f"£{s_price}" if s_price != "—" else "—")
                cols[2].markdown(f"{s_count} sold" if s_count else "")
                if s_url:
                    with cols[3]:
                        st.link_button("View →", s_url)

        # ── Notes & Analysis ──
        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📝  Notes & Analysis
        </div>
        """, unsafe_allow_html=True)

        if result.notes:
            st.markdown(f"""
            <div style="
                background: #1E293B;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 1rem 1.2rem;
                color: #CBD5E1;
                font-size: 0.9rem;
                line-height: 1.6;
            ">
                {result.notes}
            </div>
            """, unsafe_allow_html=True)

        # ── Export Section ──
        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📥  Export
        </div>
        """, unsafe_allow_html=True)

        from export import export_to_csv, export_to_json

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            csv_data = export_to_csv(result)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"ebay_hunter_{result.product_name.replace(' ', '_')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with exp_col2:
            json_data = export_to_json(result)
            st.download_button(
                label="Download JSON",
                data=json_data,
                file_name=f"ebay_hunter_{result.product_name.replace(' ', '_')}.json",
                mime="application/json",
                use_container_width=True,
            )

        # Track Price + Watch buttons
        if result.ebay_avg_price > 0:
            btn_col1, btn_col2 = st.columns(2)

            with btn_col1:
                if st.button("📈 Track This Product", use_container_width=True):
                    from tracker.price_tracker import add_to_tracker
                    supplier_url = ""
                    supplier_name = ""
                    supplier_price = 0
                    if result.suppliers:
                        supplier_url = result.suppliers[0].get("url", "")
                        supplier_name = result.suppliers[0].get("name", "")
                        supplier_price = result.suppliers[0].get("price", 0)

                    tracked = add_to_tracker(
                        product_name=result.product_name,
                        ebay_url=result.sources[0] if result.sources else "",
                        ebay_price=result.ebay_avg_price,
                        target_price=result.ebay_avg_price * 0.9,
                        supplier_price=supplier_price,
                        supplier_url=supplier_url,
                        supplier_name=supplier_name,
                    )
                    if tracked:
                        st.success(f"Added to Price Tracker!")
                    else:
                        st.error("Failed to add")

            with btn_col2:
                if st.button("⭐ Watch This Product", use_container_width=True):
                    from watchlist.items import add_to_watchlist
                    supplier_url = ""
                    supplier_name = ""
                    supplier_price = 0
                    if result.suppliers:
                        supplier_url = result.suppliers[0].get("url", "")
                        supplier_name = result.suppliers[0].get("name", "")
                        supplier_price = result.suppliers[0].get("price", 0)

                    watched = add_to_watchlist(
                        product_name=result.product_name,
                        ebay_url=result.sources[0] if result.sources else "",
                        ebay_price=result.ebay_avg_price,
                        target_price=result.ebay_avg_price * 0.9,
                        supplier_price=supplier_price,
                        supplier_url=supplier_url,
                        supplier_name=supplier_name,
                    )
                    if watched:
                        st.success(f"Added to Watchlist!")
                    else:
                        st.error("Failed to add")

        if result.sources:
            with st.expander("Sources"):
                for src in result.sources[:10]:
                    st.markdown(f"- [{src}]({src})")

        if result.raw_analysis:
            with st.expander("Raw LLM Analysis"):
                st.code(result.raw_analysis, language=None)


# ─── Bulk Analysis Tab ─────────────────────────────────────────

def render_bulk_analysis_tab():
    """Render the bulk analysis tab for multiple products."""
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.1rem; font-weight: 600; margin: 0.5rem 0 1rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 8px;">
        📦  Bulk Analysis
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    Enter multiple products to analyze at once. Each line = one product.
    """)

    # Text area for products
    products_text = st.text_area(
        "Products (one per line)",
        placeholder="wireless earbuds\nbluetooth speaker\nphone case\nlaptop stand",
        height=150,
        key="bulk_products",
    )

    # Analyze button
    if st.button("Analyze All Products", type="primary", use_container_width=True):
        if not products_text.strip():
            st.warning("Please enter at least one product.")
            return

        products = [p.strip() for p in products_text.strip().split("\n") if p.strip()]
        if not products:
            st.warning("No valid products entered.")
            return

        st.info(f"Analyzing {len(products)} products...")

        results = []
        progress = st.progress(0)
        status = st.empty()

        for i, product in enumerate(products):
            status.text(f"Analyzing: {product} ({i+1}/{len(products)})")
            progress.progress((i) / len(products))

            try:
                from deep_search import deep_search_fast
                result = deep_search_fast(product)
                results.append(result)
            except Exception as e:
                st.error(f"Failed to analyze '{product}': {e}")

        progress.progress(1.0)
        status.text("Complete!")

        if results:
            st.session_state["bulk_results"] = results
            st.success(f"Analyzed {len(results)} products successfully!")

    # Display results if available
    if "bulk_results" in st.session_state and st.session_state["bulk_results"]:
        results = st.session_state["bulk_results"]

        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📊  Results
        </div>
        """, unsafe_allow_html=True)

        # Summary table
        for i, result in enumerate(results):
            verdict = result.verdict.upper() if result.verdict else "PENDING"
            icon = "✅" if verdict == "PASS" else "❌" if verdict == "FAIL" else "⏳"

            with st.expander(f"{icon} {result.product_name} — {verdict}", expanded=False):
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Sold (30d)", f"{result.ebay_total_sold_30d}" if result.ebay_total_sold_30d else "—")
                m2.metric("Avg Price", f"£{result.ebay_avg_price:.2f}" if result.ebay_avg_price else "—")
                m3.metric("Profit", f"£{result.profit:.2f}" if result.profit else "—")
                m4.metric("Margin", f"{result.margin:.1f}%" if result.margin else "—")

                # Show what's missing for PENDING
                if verdict == "PENDING":
                    missing = []
                    if not result.ebay_avg_price:
                        missing.append("eBay sold data")
                    if not result.best_supplier_price:
                        missing.append("Supplier prices")
                    if missing:
                        st.warning(f"Missing data: {', '.join(missing)}. Try Deep Search tab for full analysis.")

                # Show suppliers with full details
                if result.suppliers:
                    st.markdown("**Suppliers:**")
                    for j, s in enumerate(result.suppliers[:3]):
                        sname = s.get("name", f"Supplier {j+1}")
                        sprice = s.get("price", 0)
                        delivery = s.get("delivery_days", "?")
                        rating = s.get("seller_rating", "")
                        orders = s.get("seller_orders", "")
                        url = s.get("url", "")

                        cols = st.columns([3, 1, 1, 1])
                        cols[0].markdown(f"**{sname}**")
                        cols[1].markdown(f"£{sprice:.2f}")
                        cols[2].markdown(f"{delivery}d")
                        if url:
                            with cols[3]:
                                st.link_button("View →", url, key=f"bulk_supplier_{i}_{j}")

                        # Show rating and orders if available
                        if rating or orders:
                            detail_cols = st.columns(3)
                            if rating:
                                detail_cols[0].caption(f"Rating: {rating}")
                            if orders:
                                detail_cols[1].caption(f"Orders: {orders}")

                # Export buttons
                from export import export_to_csv, export_to_json
                exp_col1, exp_col2 = st.columns(2)
                with exp_col1:
                    csv_data = export_to_csv(result)
                    st.download_button(
                        label="Download CSV",
                        data=csv_data,
                        file_name=f"ebay_hunter_{result.product_name.replace(' ', '_')}.csv",
                        mime="text/csv",
                        key=f"bulk_csv_{i}",
                        use_container_width=True,
                    )
                with exp_col2:
                    json_data = export_to_json(result)
                    st.download_button(
                        label="Download JSON",
                        data=json_data,
                        file_name=f"ebay_hunter_{result.product_name.replace(' ', '_')}.json",
                        mime="application/json",
                        key=f"bulk_json_{i}",
                        use_container_width=True,
                    )

        # Bulk export buttons
        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📥  Export All Results
        </div>
        """, unsafe_allow_html=True)

        from export import export_bulk_to_csv, export_bulk_to_json

        bulk_col1, bulk_col2 = st.columns(2)
        with bulk_col1:
            bulk_csv = export_bulk_to_csv(results)
            st.download_button(
                label="Download All CSV",
                data=bulk_csv,
                file_name="ebay_hunter_bulk_results.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with bulk_col2:
            bulk_json = export_bulk_to_json(results)
            st.download_button(
                label="Download All JSON",
                data=bulk_json,
                file_name="ebay_hunter_bulk_results.json",
                mime="application/json",
                use_container_width=True,
            )


# ─── Category Hunter Tab ────────────────────────────────────────

def render_category_hunter_tab():
    """Render the Category Hunter tab for auto-scanning eBay categories."""
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.1rem; font-weight: 600; margin: 0.5rem 0 1rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 8px;">
        🎯  Category Hunter
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    Auto-scan eBay categories to find profitable products — no manual searching needed.
    """)

    # Configuration
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        from hunter.category_scan import EBAY_CATEGORIES
        category = st.selectbox(
            "Category",
            options=list(EBAY_CATEGORIES.keys()),
            key="hunter_category",
        )

    with col2:
        price_range = st.slider(
            "Price Range (£)",
            min_value=0,
            max_value=100,
            value=(5, 25),
            key="hunter_price_range",
        )

    with col3:
        max_results = st.selectbox(
            "Max Products",
            options=[10, 20, 50, 100],
            index=1,
            key="hunter_max_results",
        )

    with col4:
        min_margin = st.slider(
            "Min Margin %",
            min_value=0,
            max_value=50,
            value=25,
            key="hunter_min_margin",
        )

    # Start button
    if st.button("🔍  Start Hunting", type="primary", use_container_width=True):
        price_min, price_max = price_range

        # Progress display
        progress_bar = st.progress(0)
        status = st.empty()

        # Step 1: Category Scan
        status.text("Step 1/5: Fetching eBay listings...")
        from hunter.category_scan import scan_category
        products = scan_category(category, price_min, price_max, max_results)
        progress_bar.progress(0.2)
        status.text(f"Step 1/5: Found {len(products)} listings")

        if not products:
            st.error("No products found in this category. Try different settings.")
            return

        # Step 2: Demand Check
        status.text("Step 2/5: Checking demand...")
        from hunter.demand_check import batch_demand_check

        def demand_progress(i, total, title):
            status.text(f"Step 2/5: Checking demand ({i+1}/{total})...")

        products_with_demand = batch_demand_check(
            products, 
            min_sold_30d=10, 
            min_sold_7d=1,
            progress_callback=demand_progress,
        )
        progress_bar.progress(0.4)
        status.text(f"Step 2/5: {len(products_with_demand)} products with demand")

        # Step 3: Supplier Lookup
        status.text("Step 3/5: Finding suppliers...")
        from hunter.supplier_lookup import batch_supplier_lookup

        def supplier_progress(i, total, title):
            status.text(f"Step 3/5: Finding suppliers ({i+1}/{total})...")

        products_with_supplier = batch_supplier_lookup(
            products_with_demand,
            progress_callback=supplier_progress,
        )
        progress_bar.progress(0.7)
        status.text(f"Step 3/5: {len(products_with_supplier)} products with suppliers")

        # Step 4: Profit Calculation
        status.text("Step 4/5: Calculating profit...")
        from hunter.profit_calc import batch_profit_calc
        from config import FILTERS
        filters = FILTERS.copy()
        filters["margin_min"] = float(min_margin)
        products_final = batch_profit_calc(products_with_supplier, filters)
        progress_bar.progress(0.9)
        status.text(f"Step 4/5: {sum(1 for p in products_final if p.verdict == 'PASS')} products PASS")

        # Step 5: Generate Report
        status.text("Step 5/5: Generating report...")
        from hunter.report import generate_report
        report = generate_report(
            products_final,
            category,
            price_min,
            price_max,
            total_scanned=len(products),
            total_with_demand=len(products_with_demand),
            total_with_supplier=len(products_with_supplier),
        )
        progress_bar.progress(1.0)
        status.text("Complete!")

        # Save to session state
        st.session_state["hunter_report"] = report
        st.session_state["hunter_products"] = products_final
        st.success(f"Hunt complete! Found {report.total_pass} profitable products.")

    # Display results if available
    if "hunter_report" in st.session_state and st.session_state["hunter_report"]:
        report = st.session_state["hunter_report"]
        products = st.session_state["hunter_products"]

        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📊  Category Report
        </div>
        """, unsafe_allow_html=True)

        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Scanned", f"{report.total_scanned}")
        m2.metric("With Demand", f"{report.total_with_demand}")
        m3.metric("With Supplier", f"{report.total_with_supplier}")
        m4.metric("PASS", f"{report.total_pass}", delta=f"{report.total_pass}/{report.total_scanned}")

        # Products table
        for i, p in enumerate(products[:20], 1):
            verdict = p.verdict
            icon = "✅" if verdict == "PASS" else "❌" if verdict == "FAIL" else "⏳"

            with st.expander(f"{icon} {i}. {p.title} — {verdict}", expanded=False):
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("eBay Price", f"£{p.price:.2f}")
                c2.metric("Supplier Price", f"£{p.supplier_price:.2f}")
                c3.metric("Profit", f"£{p.profit:.2f}")
                c4.metric("Margin", f"{p.margin:.1f}%")
                c5.metric("Sold (30d)", f"{p.sold_30d}")

                if p.supplier_name:
                    st.caption(f"Supplier: {p.supplier_name}")

                link_cols = st.columns(2)
                with link_cols[0]:
                    if p.url:
                        st.link_button("eBay Listing →", p.url, key=f"ebay_{i}")
                with link_cols[1]:
                    if p.supplier_url:
                        st.link_button("Supplier →", p.supplier_url, key=f"supplier_{i}")

        # Export buttons
        st.markdown("""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            📥  Export Report
        </div>
        """, unsafe_allow_html=True)

        from hunter.report import export_report_csv, export_report_json

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            csv_data = export_report_csv(report)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"hunter_{report.category.replace(' ', '_')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with exp_col2:
            json_data = export_report_json(report)
            st.download_button(
                label="Download JSON",
                data=json_data,
                file_name=f"hunter_{report.category.replace(' ', '_')}.json",
                mime="application/json",
                use_container_width=True,
            )


# ─── Price Tracker Tab ──────────────────────────────────────────

def render_price_tracker_tab():
    """Render the Price Tracker tab."""
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.1rem; font-weight: 600; margin: 0.5rem 0 1rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 8px;">
        📈  Price Tracker
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    Track product prices over time and get alerts when prices drop.
    """)

    # Alerts section
    from tracker.alerts import get_alerts, get_unread_count, mark_alert_read
    unread_count = get_unread_count()

    if unread_count > 0:
        st.markdown(f"""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            🔔  Alerts ({unread_count} unread)
        </div>
        """, unsafe_allow_html=True)

        alerts = get_alerts(unread_only=True)
        for alert in alerts[:5]:
            icon = "🔔" if alert["alert_type"] == "price_drop" else "📈"
            cols = st.columns([4, 1])
            with cols[0]:
                st.markdown(f"{icon} {alert['message']}")
            with cols[1]:
                if st.button("✓", key=f"read_alert_{alert['id']}"):
                    mark_alert_read(alert["id"])
                    st.rerun()

    # Controls
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1rem 0 0.6rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 6px;">
        📦  Tracked Products
    </div>
    """, unsafe_allow_html=True)

    # Add new product form
    with st.expander("➕ Add Product to Track", expanded=False):
        add_col1, add_col2 = st.columns(2)
        with add_col1:
            new_product_name = st.text_input("Product Name", key="new_track_name")
            new_ebay_url = st.text_input("eBay URL", key="new_track_url")
        with add_col2:
            new_ebay_price = st.number_input("Current Price (£)", min_value=0.0, step=0.01, key="new_track_price")
            new_target_price = st.number_input("Target Price (£)", min_value=0.0, step=0.01, key="new_track_target")

        if st.button("Add to Tracker", type="primary"):
            if new_product_name and new_ebay_url:
                from tracker.price_tracker import add_to_tracker
                result = add_to_tracker(
                    product_name=new_product_name,
                    ebay_url=new_ebay_url,
                    ebay_price=new_ebay_price,
                    target_price=new_target_price,
                )
                if result:
                    st.success(f"Added '{new_product_name}' to tracker!")
                    st.rerun()
                else:
                    st.error("Failed to add product")
            else:
                st.warning("Please fill in product name and URL")

    # Check all prices button
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption("Auto-check: Every 6 hours")
    with col2:
        if st.button("🔄 Check All Prices", use_container_width=True):
            from tracker.price_checker import check_all_prices

            progress = st.progress(0)
            status = st.empty()

            def check_progress(i, total, name):
                status.text(f"Checking: {name} ({i+1}/{total})")
                progress.progress((i) / total if total > 0 else 0)

            results = check_all_prices(progress_callback=check_progress)
            progress.progress(1.0)
            status.text(f"Complete! Checked {results['checked']} products, {results['alerts']} alerts")
            st.rerun()

    # Display tracked products
    from tracker.price_tracker import get_tracked_products, remove_from_tracker, toggle_alert
    from tracker.history import get_price_trend

    products = get_tracked_products()

    if not products:
        st.info("No products tracked yet. Add one above to get started.")
        return

    for product in products:
        with st.expander(
            f"{'🔔' if product['alert_enabled'] else '🔕'} {product['product_name']} — £{product['ebay_price']:.2f}",
            expanded=False,
        ):
            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("eBay Price", f"£{product['ebay_price']:.2f}")
            m2.metric("Target Price", f"£{product['target_price']:.2f}" if product['target_price'] > 0 else "—")
            m3.metric("Supplier Price", f"£{product['supplier_price']:.2f}" if product['supplier_price'] > 0 else "—")

            # Price trend
            trend = get_price_trend(product["id"], days=7)
            trend_icon = "📈" if trend["trend"] == "up" else "📉" if trend["trend"] == "down" else "➡️"
            m4.metric("7d Trend", f"{trend_icon} {trend['change_percent']:+.1f}%")

            # Last checked
            if product["last_checked"]:
                st.caption(f"Last checked: {product['last_checked']}")

            # Action buttons
            btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

            with btn_col1:
                if product["ebay_url"]:
                    st.link_button("View eBay →", product["ebay_url"], key=f"track_ebay_{product['id']}")

            with btn_col2:
                if st.button("🔔 Alert", key=f"toggle_alert_{product['id']}"):
                    toggle_alert(product["id"])
                    st.rerun()

            with btn_col3:
                if st.button("🔄 Check", key=f"check_now_{product['id']}"):
                    from tracker.price_checker import check_single_price
                    new_price = check_single_price(product["id"])
                    if new_price:
                        st.success(f"Updated: £{new_price:.2f}")
                        st.rerun()

            with btn_col4:
                if st.button("🗑️ Remove", key=f"remove_{product['id']}"):
                    remove_from_tracker(product["id"])
                    st.rerun()


# ─── Watchlist Tab ──────────────────────────────────────────────

def render_watchlist_tab():
    """Render the Watchlist & Saved Searches tab."""
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.1rem; font-weight: 600; margin: 0.5rem 0 1rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 8px;">
        ⭐  Watchlist & Saved Searches
    </div>
    """, unsafe_allow_html=True)

    from watchlist import (
        get_watchlist_items, remove_from_watchlist,
        get_saved_searches, save_search, delete_search,
        run_search, run_all_searches,
        get_new_results, mark_result_read, get_unread_results_count,
    )

    # ── New Finds (Unread Results) ──
    unread_count = get_unread_results_count()
    if unread_count > 0:
        st.markdown(f"""
        <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1rem 0 0.6rem 0;
                     border-bottom: 1px solid #334155; padding-bottom: 6px;">
            🔔  New Finds ({unread_count})
        </div>
        """, unsafe_allow_html=True)

        new_results = get_new_results(unread_only=True)
        for r in new_results[:5]:
            cols = st.columns([4, 1])
            with cols[0]:
                st.markdown(f"🔔 **{r['product_name']}** found by *{r['search_name']}* — £{r['ebay_price']:.2f} ({r['margin']:.1f}% margin)")
            with cols[1]:
                if st.button("✓", key=f"read_result_{r['id']}"):
                    mark_result_read(r["id"])
                    st.rerun()

    # ── Watchlist Items ──
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1rem 0 0.6rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 6px;">
        ⭐  Watchlist Items
    </div>
    """, unsafe_allow_html=True)

    # Add to watchlist form
    with st.expander("➕ Add to Watchlist", expanded=False):
        w_col1, w_col2 = st.columns(2)
        with w_col1:
            w_name = st.text_input("Product Name", key="watch_name")
            w_url = st.text_input("eBay URL", key="watch_url")
        with w_col2:
            w_price = st.number_input("eBay Price (£)", min_value=0.0, step=0.01, key="watch_price")
            w_target = st.number_input("Target Price (£)", min_value=0.0, step=0.01, key="watch_target")

        if st.button("⭐ Add to Watchlist", type="primary"):
            if w_name:
                from watchlist.items import add_to_watchlist
                result = add_to_watchlist(
                    product_name=w_name,
                    ebay_url=w_url,
                    ebay_price=w_price,
                    target_price=w_target,
                )
                if result:
                    st.success(f"Added '{w_name}' to watchlist!")
                    st.rerun()
            else:
                st.warning("Please enter product name")

    watchlist_items = get_watchlist_items()

    if not watchlist_items:
        st.info("Watchlist is empty. Add products above.")
    else:
        for item in watchlist_items:
            with st.expander(
                f"⭐ {item['product_name']} — £{item['ebay_price']:.2f}",
                expanded=False,
            ):
                m1, m2, m3 = st.columns(3)
                m1.metric("eBay Price", f"£{item['ebay_price']:.2f}")
                m2.metric("Target Price", f"£{item['target_price']:.2f}" if item['target_price'] > 0 else "—")
                m3.metric("Supplier Price", f"£{item['supplier_price']:.2f}" if item['supplier_price'] > 0 else "—")

                btn_cols = st.columns(3)
                with btn_cols[0]:
                    if item['ebay_url']:
                        st.link_button("View eBay →", item['ebay_url'], key=f"watch_ebay_{item['id']}")
                with btn_cols[1]:
                    if item['supplier_url']:
                        st.link_button("Supplier →", item['supplier_url'], key=f"watch_supplier_{item['id']}")
                with btn_cols[2]:
                    if st.button("🗑️ Remove", key=f"watch_remove_{item['id']}"):
                        remove_from_watchlist(item["id"])
                        st.rerun()

    # ── Saved Searches ──
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 6px;">
        🔍  Saved Searches
    </div>
    """, unsafe_allow_html=True)

    saved_searches = get_saved_searches()

    # Run All button
    if saved_searches:
        if st.button("▶️ Run All Searches", use_container_width=True):
            progress = st.progress(0)
            status = st.empty()

            def search_progress(i, total, name):
                status.text(f"Running: {name} ({i+1}/{total})")
                progress.progress((i) / total if total > 0 else 0)

            results = run_all_searches(progress_callback=search_progress)
            progress.progress(1.0)
            status.text(f"Complete! {results['searches_run']} searches, {results['total_found']} new finds")
            st.rerun()

    # Display saved searches
    if saved_searches:
        for search in saved_searches:
            with st.expander(
                f"🔍 {search['search_name']} — \"{search['query']}\"",
                expanded=False,
            ):
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Price Range", f"£{search['price_min']:.0f}-£{search['price_max']:.0f}")
                s2.metric("Min Margin", f"{search['min_margin']:.0f}%")
                s3.metric("Total Finds", search['result_count'])
                s4.metric("Unread", search['unread_count'])

                if search['last_run']:
                    st.caption(f"Last run: {search['last_run']}")

                btn_cols = st.columns(3)
                with btn_cols[0]:
                    if st.button("▶️ Run Now", key=f"run_search_{search['id']}"):
                        with st.spinner("Running search..."):
                            result = run_search(search["id"])
                        if result["found"] > 0:
                            st.success(f"Found {result['found']} new products!")
                        else:
                            st.info("No new products found")
                        st.rerun()
                with btn_cols[1]:
                    if st.button("✏️ Toggle Auto", key=f"toggle_auto_{search['id']}"):
                        from watchlist.searches import update_search
                        update_search(search["id"], auto_run=not search["auto_run"])
                        st.rerun()
                with btn_cols[2]:
                    if st.button("🗑️ Delete", key=f"delete_search_{search['id']}"):
                        delete_search(search["id"])
                        st.rerun()
    else:
        st.info("No saved searches yet. Create one below.")

    # ── Save New Search ──
    st.markdown("""
    <div style="color: #E2E8F0; font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem 0;
                 border-bottom: 1px solid #334155; padding-bottom: 6px;">
        ➕  Save New Search
    </div>
    """, unsafe_allow_html=True)

    ns_col1, ns_col2 = st.columns(2)
    with ns_col1:
        ns_name = st.text_input("Search Name", key="new_search_name")
        ns_query = st.text_input("Query", key="new_search_query")
    with ns_col2:
        ns_price_range = st.slider("Price Range (£)", 0, 100, (5, 25), key="new_search_price")
        ns_margin = st.slider("Min Margin %", 0, 50, 25, key="new_search_margin")

    if st.button("💾 Save Search", type="primary"):
        if ns_name and ns_query:
            result = save_search(
                search_name=ns_name,
                query=ns_query,
                price_min=ns_price_range[0],
                price_max=ns_price_range[1],
                min_margin=float(ns_margin),
            )
            if result:
                st.success(f"Saved '{ns_name}'!")
                st.rerun()
        else:
            st.warning("Please fill in name and query")


# ─── Main ───────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="eBay Hunter — Product Sourcing Intelligence",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()
    render_sidebar()

    # Hero banner (only on main view, not product detail)
    if "selected_product_id" not in st.session_state:
        st.markdown("""
        <div style="
            background: linear-gradient(135deg, #1E3A5F 0%, #0B1120 50%, #1A1A2E 100%);
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 2rem 2.5rem;
            margin-bottom: 1.5rem;
            position: relative;
            overflow: hidden;
        ">
            <div style="position: absolute; top: 0; right: 0; width: 300px; height: 300px;
                        background: radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%);
                        pointer-events: none;"></div>
            <h1 style="color: #F8FAFC; font-size: 1.8rem; font-weight: 700; margin: 0 0 0.3rem 0;
                       letter-spacing: -0.02em;">
                eBay Hunter
            </h1>
            <p style="color: #94A3B8; font-size: 0.95rem; margin: 0; max-width: 600px;">
                Product sourcing intelligence — find profitable items, verify suppliers,
                and get AI-powered verdicts in seconds.
            </p>
        </div>
        """, unsafe_allow_html=True)

    # Check if we're viewing a product detail
    if "selected_product_id" in st.session_state:
        render_product_detail(st.session_state["selected_product_id"])
        return

    # Main tabs
    tab_analyze, tab_deep, tab_bulk, tab_hunter, tab_tracker, tab_watch, tab_history = st.tabs(
        ["🔍  Analyze", "🔬  Deep Search", "📦  Bulk Analysis", "🎯  Category Hunter", "📈  Price Tracker", "⭐  Watchlist", "📋  History"]
    )

    with tab_analyze:
        render_analyze_tab()

    with tab_deep:
        render_deep_search_tab()

    with tab_bulk:
        render_bulk_analysis_tab()

    with tab_hunter:
        render_category_hunter_tab()

    with tab_tracker:
        render_price_tracker_tab()

    with tab_watch:
        render_watchlist_tab()

    with tab_history:
        render_history_tab()


if __name__ == "__main__":
    main()
