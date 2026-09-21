"""
Custom filter persistence — save/load user filter presets to JSON.

Usage:
    from utils.filters import load_filters, save_filters, reset_filters, list_presets
"""

import json
from pathlib import Path
from config import FILTERS

FILTERS_FILE = Path(__file__).parent.parent / "data" / "custom_filters.json"


def _ensure_file():
    FILTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FILTERS_FILE.exists():
        FILTERS_FILE.write_text(json.dumps({"active": FILTERS, "presets": {}}, indent=2))


def _load() -> dict:
    _ensure_file()
    try:
        return json.loads(FILTERS_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {"active": FILTERS, "presets": {}}


def _save(data: dict):
    _ensure_file()
    FILTERS_FILE.write_text(json.dumps(data, indent=2))


def load_filters() -> dict:
    """Load the active custom filters."""
    data = _load()
    return data.get("active", FILTERS)


def save_filters(filters: dict):
    """Save current active filters."""
    data = _load()
    data["active"] = filters
    _save(data)


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


def is_delivery_exception合格(supplier_name: str, sold_30d: int, filters: dict) -> bool:
    """Check if supplier qualifies for delivery exception (long delivery allowed for high demand)."""
    supplier_type = get_supplier_type(supplier_name)
    
    # Retailers always pass delivery check
    if supplier_type == "retailer":
        return True
    
    # Dropshippers with high demand (>=30 sold/month) can have longer delivery
    if sold_30d >= 30:
        return True
    
    # Otherwise check against max delivery
    delivery_min, delivery_max = get_supplier_delivery_range(supplier_name)
    max_allowed = filters.get("delivery_exception_max", 25)
    return delivery_max <= max_allowed


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
