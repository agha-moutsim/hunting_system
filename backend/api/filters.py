"""Active filter settings — read / update the user-adjustable price range (PR-5/PR-7)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import FILTERS
from utils.filters import active_range, load_filters, set_active_range

router = APIRouter()


class RangeUpdate(BaseModel):
    price_min: float = Field(..., gt=0)
    price_max: float = Field(..., gt=0)


@router.get("/filters")
def get_filters():
    """Current active filters (incl. the user-adjusted range) + config defaults."""
    return {
        "active": load_filters(),
        "range": active_range(),
        "defaults": {"price_min": FILTERS["price_min"], "price_max": FILTERS["price_max"]},
    }


@router.put("/filters")
def update_filters(req: RangeUpdate):
    """Set the active price range. Invalid ranges are rejected (422) — the
    gate can never be poisoned through the API (PR-7, single validation)."""
    try:
        rng = set_active_range(req.price_min, req.price_max)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"range": rng}
