"""Saved searches — save and manage search queries."""

from typing import Optional

from db.database import SessionLocal
from db.models import SavedSearch
from config import FILTERS


def save_search(
    search_name: str,
    query: str,
    category: str = "",
    price_min: float = FILTERS["price_min"],
    price_max: float = FILTERS["price_max"],
    min_margin: float = 25.0,
    auto_run: bool = True,
) -> Optional[SavedSearch]:
    """Save a search query."""
    db = SessionLocal()
    try:
        # Check if already exists by name
        existing = db.query(SavedSearch).filter(SavedSearch.search_name == search_name).first()
        if existing:
            # Update existing
            existing.query = query
            existing.category = category
            existing.price_min = price_min
            existing.price_max = price_max
            existing.min_margin = min_margin
            existing.auto_run = auto_run
            db.commit()
            db.refresh(existing)
            return existing

        # Create new
        search = SavedSearch(
            search_name=search_name,
            query=query,
            category=category,
            price_min=price_min,
            price_max=price_max,
            min_margin=min_margin,
            auto_run=auto_run,
        )
        db.add(search)
        db.commit()
        db.refresh(search)
        return search

    except Exception as e:
        print(f"[ERROR] Failed to save search: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def delete_search(search_id: int) -> bool:
    """Delete a saved search."""
    db = SessionLocal()
    try:
        search = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if search:
            db.delete(search)
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to delete search: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_saved_searches() -> list[dict]:
    """Get all saved searches."""
    db = SessionLocal()
    try:
        searches = db.query(SavedSearch).order_by(SavedSearch.created_at.desc()).all()
        return [
            {
                "id": s.id,
                "search_name": s.search_name,
                "query": s.query,
                "category": s.category,
                "price_min": s.price_min,
                "price_max": s.price_max,
                "min_margin": s.min_margin,
                "auto_run": s.auto_run,
                "last_run": s.last_run.isoformat() if s.last_run else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "result_count": len(s.results),
                "unread_count": sum(1 for r in s.results if not r.is_read),
            }
            for s in searches
        ]
    except Exception as e:
        print(f"[ERROR] Failed to get saved searches: {e}")
        return []
    finally:
        db.close()


def update_search(search_id: int, **kwargs) -> bool:
    """Update a saved search."""
    db = SessionLocal()
    try:
        search = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        if not search:
            return False

        for key, value in kwargs.items():
            if hasattr(search, key):
                setattr(search, key, value)

        db.commit()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update search: {e}")
        db.rollback()
        return False
    finally:
        db.close()
