"""Watchlist + Saved Searches endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import SearchCreate, WatchlistCreate

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Watchlist items ─────────────────────────────────────────────

@router.get("/watchlist")
def list_watchlist():
    """Watchlist items — out-of-band rows filtered + counted (PR-2 layer 4)."""
    from watchlist import get_watchlist_items
    from engine.price_gate import excluded_note, in_band

    items = get_watchlist_items()
    kept = [i for i in items if in_band(i.get("ebay_price")) or not i.get("ebay_price")]
    excluded = len(items) - len(kept)
    resp = {"items": kept}
    if excluded:
        resp["excluded_note"] = excluded_note("watchlist items", excluded)
    return resp


@router.post("/watchlist")
def create_watchlist(req: WatchlistCreate):
    from watchlist import add_to_watchlist
    from engine.price_gate import band_label, in_band

    # PR-6 write gate: never store an out-of-band entry price
    if req.ebay_price and not in_band(req.ebay_price):
        raise HTTPException(
            status_code=422,
            detail=(
                f"This listing is £{req.ebay_price:.2f} — outside your "
                f"{band_label()} band."
            ),
        )

    item = add_to_watchlist(
        product_name=req.product_name,
        ebay_url=req.ebay_url,
        ebay_price=req.ebay_price,
        target_price=req.target_price,
        supplier_price=req.supplier_price,
        supplier_url=req.supplier_url,
        supplier_name=req.supplier_name,
        notes=req.notes,
    )
    if not item:
        raise HTTPException(status_code=500, detail="Failed to add to watchlist")
    return {"id": item.id, "product_name": item.product_name}


@router.delete("/watchlist/{item_id}")
def delete_watchlist(item_id: int):
    from watchlist import remove_from_watchlist

    if not remove_from_watchlist(item_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


# ── Saved searches ──────────────────────────────────────────────

@router.get("/searches")
def list_searches():
    from watchlist import get_saved_searches
    from engine.price_gate import PRICE_MAX, PRICE_MIN

    searches = get_saved_searches()
    # PR-7: any band stored before clamping existed is re-clamped on read
    for s in searches:
        s["price_min"] = max(s.get("price_min") or PRICE_MIN, PRICE_MIN)
        s["price_max"] = min(s.get("price_max") or PRICE_MAX, PRICE_MAX)
    return {"searches": searches}


@router.post("/searches")
def create_search(req: SearchCreate):
    from watchlist import save_search
    from engine.price_gate import PRICE_MIN, PRICE_MAX

    s = save_search(
        search_name=req.search_name,
        query=req.query,
        category=req.category,
        # PR-7: stored searches cannot widen the band
        price_min=max(req.price_min, PRICE_MIN),
        price_max=min(req.price_max, PRICE_MAX),
        min_margin=req.min_margin,
        auto_run=req.auto_run,
    )
    if not s:
        raise HTTPException(status_code=500, detail="Failed to save search")
    return {"id": s.id, "search_name": s.search_name}


@router.delete("/searches/{search_id}")
def delete_search(search_id: int):
    from watchlist import delete_search as _delete

    if not _delete(search_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


@router.post("/searches/{search_id}/run")
def run_search(search_id: int):
    from watchlist import run_search as _run

    return _run(search_id)


@router.post("/searches/run-all")
def run_all_searches():
    from watchlist import run_all_searches as _run_all

    return _run_all()


@router.get("/searches/results")
def new_results(unread_only: bool = True, limit: int = 50):
    from watchlist import get_new_results, get_unread_results_count

    return {
        "results": get_new_results(unread_only=unread_only, limit=limit),
        "unread_count": get_unread_results_count(),
    }


@router.post("/searches/results/{result_id}/read")
def mark_result_read(result_id: int):
    from watchlist import mark_result_read

    return {"ok": mark_result_read(result_id)}
