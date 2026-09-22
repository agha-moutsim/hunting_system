"""Run saved searches and find new products."""

from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import SavedSearch, SearchResult
from watchlist.searches import mark_last_run


def run_search(search_id: int) -> dict:
    """Run a single saved search and store results."""
    db = SessionLocal()
    try:
        search = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if not search:
            return {"found": 0, "error": "Search not found"}

        # Run the search using fast analysis
        from deep_search import deep_search_fast

        results_found = 0

        try:
            result = deep_search_fast(search.query)

            # Check if it meets filters
            if result.ebay_avg_price > 0 and result.best_supplier_price > 0:
                # Check price filter
                price_ok = search.price_min <= result.best_supplier_price <= search.price_max

                # Check margin filter
                margin_ok = result.margin >= search.min_margin

                if price_ok and margin_ok and result.profit > 0:
                    # Check if this result already exists (by URL)
                    existing = db.query(SearchResult).filter(
                        SearchResult.search_id == search_id,
                        SearchResult.ebay_url == (result.sources[0] if result.sources else ""),
                    ).first()

                    if not existing:
                        # Get first supplier URL
                        supplier_url = ""
                        supplier_name = ""
                        if result.suppliers:
                            supplier_url = result.suppliers[0].get("url", "")
                            supplier_name = result.suppliers[0].get("name", "")

                        search_result = SearchResult(
                            search_id=search_id,
                            product_name=result.product_name,
                            ebay_url=result.sources[0] if result.sources else "",
                            ebay_price=result.ebay_avg_price,
                            supplier_price=result.best_supplier_price,
                            supplier_url=supplier_url,
                            supplier_name=supplier_name,
                            profit=result.profit,
                            margin=result.margin,
                            verdict=result.verdict,
                        )
                        db.add(search_result)
                        results_found += 1

        except Exception as e:
            print(f"[WARN] Search execution failed: {e}")

        db.commit()
        mark_last_run(search_id)

        return {"found": results_found, "error": None}

    except Exception as e:
        print(f"[ERROR] Failed to run search: {e}")
        db.rollback()
        return {"found": 0, "error": str(e)}
    finally:
        db.close()


def run_all_searches(progress_callback=None) -> dict:
    """Run all auto-run saved searches."""
    db = SessionLocal()
    try:
        searches = db.query(SavedSearch).filter(SavedSearch.auto_run == True).all()
        total_found = 0
        total_searches = len(searches)

        for i, search in enumerate(searches):
            if progress_callback:
                progress_callback(i, total_searches, search.search_name)

            result = run_search(search.id)
            total_found += result.get("found", 0)

        return {"searches_run": total_searches, "total_found": total_found}

    except Exception as e:
        print(f"[ERROR] Failed to run all searches: {e}")
        return {"searches_run": 0, "total_found": 0, "error": str(e)}
    finally:
        db.close()


def get_new_results(unread_only: bool = True, limit: int = 50) -> list[dict]:
    """Get search results (new finds)."""
    db = SessionLocal()
    try:
        query = db.query(SearchResult).join(SavedSearch)

        if unread_only:
            query = query.filter(SearchResult.is_read == False)

        results = query.order_by(SearchResult.found_at.desc()).limit(limit).all()

        return [
            {
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
            }
            for r in results
        ]

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
