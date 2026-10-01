"""
Custom filter persistence — save/load user filter presets to JSON.

Usage:
    from utils.filters import load_filters, save_filters, reset_filters, list_presets
"""

import json
from pathlib import Path
from config import FILTERS, ALLOWED_CONDITIONS

FILTERS_FILE = Path(__file__).parent.parent / "data" / "custom_filters.json"


def _ensure_file():
    FILTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FILTERS_FILE.exists():
        FILTERS_FILE.write_text(json.dumps({"active": FILTERS, "presets": {}}, indent=2))


_cache: dict = {"mtime": None, "data": None}


def _load() -> dict:
    _ensure_file()
    try:
        mtime = FILTERS_FILE.stat().st_mtime_ns
        if _cache["mtime"] == mtime and _cache["data"] is not None:
            return _cache["data"]
        data = json.loads(FILTERS_FILE.read_text())
        _cache["mtime"] = mtime
        _cache["data"] = data
        return data
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {"active": FILTERS, "presets": {}}


def _save(data: dict):
    _ensure_file()
    FILTERS_FILE.write_text(json.dumps(data, indent=2))
    _cache["mtime"] = None
    _cache["data"] = None


def _valid_range(lo, hi) -> bool:
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return False
    return 0 < lo < hi <= 10000


def valid_range(lo, hi) -> bool:
    """Public validity check — same single rule the gate itself uses."""
    return _valid_range(lo, hi)


def load_filters() -> dict:
    """Load the active custom filters.

    CONSTRAINTS_PRICING.md PR-5/PR-7: config.py holds the DEFAULT range;
    custom_filters.json may carry a user-adjusted range, which is the
    active gate everywhere. An invalid stored range silently falls back
    to the defaults (a poisoned file can never widen the gate), and keys
    unknown to FILTERS are dropped so stale rules cannot resurface.
    """
    data = _load()
    filters = {k: v for k, v in dict(data.get("active", FILTERS)).items() if k in FILTERS}
    for k in FILTERS:
        filters.setdefault(k, FILTERS[k])
    # C10 — an out-of-allow-list condition falls back to the default, the
    # same way an invalid range does: a poisoned file can never relax
    # New-only into "Used".
    if not (isinstance(filters.get("condition"), str)
            and filters["condition"].strip() in ALLOWED_CONDITIONS):
        filters["condition"] = FILTERS["condition"]
    else:
        filters["condition"] = filters["condition"].strip()
    if not _valid_range(filters.get("price_min"), filters.get("price_max")):
        filters["price_min"] = FILTERS["price_min"]
        filters["price_max"] = FILTERS["price_max"]
    else:
        filters["price_min"] = float(filters["price_min"])
        filters["price_max"] = float(filters["price_max"])
    return filters


def active_range() -> dict:
    """Active price range used for range semantics (PR-6)."""
    loaded = load_filters()
    return {"min": loaded["price_min"], "max": loaded["price_max"]}


def resolve_range(price_min: float | None = None, price_max: float | None = None) -> dict:
    """View range for one response — explicit params override the active range."""
    active = active_range()
    return {
        "min": active["min"] if price_min is None else price_min,
        "max": active["max"] if price_max is None else price_max,
    }


def price_in_range(price, rng: dict) -> bool:
    """True when a price falls inside rng; rows without a usable price are kept."""
    if not price:
        return True
    try:
        p = float(price)
    except (TypeError, ValueError):
        return True
    return rng["min"] <= p <= rng["max"]


def outside_range(price, rng: dict) -> bool:
    """True when a usable price falls outside rng; missing prices are never flagged."""
    if not price:
        return False
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False
    return p < rng["min"] or p > rng["max"]


def save_filters(filters: dict):
    """Save current active filters; a valid user range is kept, an invalid one stripped."""
    data = _load()
    active = {k: v for k, v in filters.items() if k in FILTERS}
    if not _valid_range(active.get("price_min"), active.get("price_max")):
        active.pop("price_min", None)
        active.pop("price_max", None)
    else:
        active["price_min"] = float(active["price_min"])
        active["price_max"] = float(active["price_max"])
    data["active"] = active
    _save(data)


def set_active_range(price_min, price_max) -> dict:
    """Persist a validated user range (PR-7); returns the new active range.

    Raises ValueError on an invalid range so the API layer can reject it —
    validation lives in exactly one place (_valid_range).
    """
    if not _valid_range(price_min, price_max):
        raise ValueError("Invalid range: need 0 < price_min < price_max <= 10000")
    merged = dict(load_filters())
    merged["price_min"] = float(price_min)
    merged["price_max"] = float(price_max)
    save_filters(merged)
    return active_range()


def set_active_condition(condition) -> str:
    """Persist the active product condition (C10).

    Raises ValueError when the value is outside ALLOWED_CONDITIONS so the
    API layer can reject it with 422 — validation lives in one place,
    exactly like _valid_range.
    """
    if not (isinstance(condition, str) and condition.strip() in ALLOWED_CONDITIONS):
        raise ValueError(
            "Invalid condition: v1 accepts only "
            + ", ".join(ALLOWED_CONDITIONS)
        )
    merged = dict(load_filters())
    merged["condition"] = condition.strip()
    save_filters(merged)
    return merged["condition"]


def reset_filters():
    """Reset to config defaults."""
    data = _load()
    data["active"] = FILTERS.copy()
    _save(data)


def get_supplier_type(supplier_name: str) -> str:
    """Get supplier type: 'retailer' or 'dropshipper'."""
    retailers = ["b&q", "toolstation", "amazon uk", "amazon"]
    dropshippers = ["aliexpress", "cj dropshipping", "godropship", "joybuy", "temu", "shein"]
    
    name_lower = supplier_name.lower()
    for r in retailers:
        if r in name_lower:
            return "retailer"
    for d in dropshippers:
        if d in name_lower:
            return "dropshipper"
    return "unknown"


def get_supplier_delivery_range(supplier_name: str) -> tuple[int, int]:
    """Get expected delivery range for a supplier (min_days, max_days)."""
    delivery_map = {
        "b&q": (1, 5),
        "toolstation": (1, 3),
        "amazon uk": (1, 2),
        "amazon": (1, 2),
        "cj dropshipping": (3, 7),
        "godropship": (7, 18),
        "joybuy": (7, 21),
        "aliexpress": (12, 25),
    }
    
    name_lower = supplier_name.lower()
    for key, (min_d, max_d) in delivery_map.items():
        if key in name_lower:
            return (min_d, max_d)
    return (7, 21)  # Default


def save_preset(name: str, filters: dict):
    """Save a named filter preset."""
    data = _load()
    if "presets" not in data:
        data["presets"] = {}
    data["presets"][name] = filters
    _save(data)


def load_preset(name: str) -> dict | None:
    """Load a named preset."""
    data = _load()
    return data.get("presets", {}).get(name)


def list_presets() -> list[str]:
    """List saved preset names."""
    data = _load()
    return list(data.get("presets", {}).keys())


def delete_preset(name: str):
    """Delete a preset."""
    data = _load()
    data.get("presets", {}).pop(name, None)
    _save(data)


def get_defaults() -> dict:
    """Return the hardcoded defaults from config.py."""
    return FILTERS.copy()
