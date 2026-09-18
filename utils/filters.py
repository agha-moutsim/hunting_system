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
