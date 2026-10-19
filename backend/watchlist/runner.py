"""Run saved searches and find new products.

The RUN itself lives in hunter/saved_searches (one implementation, with the
stated Browse budget); this module re-exports it for the watchlist surfaces
and keeps the reading side: new results, the unread count, mark-read.
"""

from db.database import SessionLocal
from db.models import SavedSearch, SearchResult
from utils.filters import active_range, outside_range, price_in_range


def run_search(search_id: int) -> dict:
    """Run a single saved search - hunter.saved_searches does the work.

    Delegated so a run from this surface and a scheduled pass are the same
    run: same rows, same stated Browse cost, same refusal sentences.
    """
    from hunter.saved_searches import run_saved_search

    return run_saved_search(search_id)


def run_all_searches(progress_callback=None) -> dict:
    """Run the auto-run saved searches, up to the stated pass budget."""
    from hunter.saved_searches import run_saved_searches

    return run_saved_searches(progress_callback=progress_callback)


def get_new_results(
    unread_only: bool = True,
    limit: int = 50,
    price_range: dict | None = None,
) -> list[dict]:
    """Get search results (new finds) — view-filtered by range, out-of-range rows flagged."""
    db = SessionLocal()
    try:
        query = db.query(SearchResult).join(SavedSearch)

        if unread_only:
            query = query.filter(SearchResult.is_read == False)

        results = query.order_by(SearchResult.found_at.desc()).limit(limit).all()

        active = active_range()
        view = price_range if price_range is not None else active
        rows = []
        for r in results:
            if not price_in_range(r.ebay_price, view):
                continue
            row = {
                "id": r.id,
                "search_id": r.search_id,
                "search_name": r.saved_search.search_name if r.saved_search else "",
                "product_name": r.product_name,
                "ebay_url": r.ebay_url,
                "ebay_price": r.ebay_price,
                "supplier_price": r.supplier_price,
                "supplier_url": r.supplier_url,
                "supplier_name": r.supplier_name,
                "profit": r.profit,
                "margin": r.margin,
                "verdict": r.verdict,
                "is_read": r.is_read,
                "found_at": r.found_at.isoformat() if r.found_at else None,
                "outside_band": outside_range(r.ebay_price, active),
            }
            rows.append(row)
        return rows

    except Exception as e:
        print(f"[ERROR] Failed to get new results: {e}")
        return []
    finally:
        db.close()


def mark_result_read(result_id: int) -> bool:
    """Mark a search result as read."""
    db = SessionLocal()
    try:
        result = db.query(SearchResult).filter(SearchResult.id == result_id).first()
        if result:
            result.is_read = True
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to mark result read: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_unread_results_count() -> int:
    """Get count of unread search results."""
    db = SessionLocal()
    try:
        return db.query(SearchResult).filter(SearchResult.is_read == False).count()
    except Exception:
        return 0
    finally:
        db.close()
