"""Active filter settings — read / update the user-adjustable price range (PR-5/PR-7)
and the product condition (C10)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import FILTERS
from utils.filters import (
    active_range,
    load_filters,
    set_active_condition,
    set_active_range,
)

router = APIRouter()


class RangeUpdate(BaseModel):
    price_min: float = Field(..., gt=0)
    price_max: float = Field(..., gt=0)
    # Optional so the existing range-only clients keep working (PR-7).
    condition: str | None = None


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
    """Set the active price range and/or condition. Invalid values are
    rejected (422) — neither the price gate nor New-only can be poisoned
    through the API (PR-7 + C10, single validation each)."""
    try:
        rng = set_active_range(req.price_min, req.price_max)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if req.condition is not None:
        try:
            set_active_condition(req.condition)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    return {"range": rng, "condition": load_filters()["condition"]}
