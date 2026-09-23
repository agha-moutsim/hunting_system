"""JSON export for eBay Hunter results."""

import json
from typing import Any

from export.format import format_to_schema, format_bulk_to_schema


def export_to_json(result: Any, pretty: bool = True) -> str:
    """Export a single result to JSON format (user's schema)."""
    formatted = format_to_schema(result)
    if pretty:
        return json.dumps(formatted, indent=2, ensure_ascii=False)
    return json.dumps(formatted, ensure_ascii=False)


def export_bulk_to_json(results: list, pretty: bool = True) -> str:
    """Export multiple results to JSON format (user's schema)."""
    formatted = format_bulk_to_schema(results)
    if pretty:
        return json.dumps(formatted, indent=2, ensure_ascii=False)
    return json.dumps(formatted, ensure_ascii=False)


def export_to_json_file(result: Any, filepath: str) -> str:
    """Export a single result to a JSON file."""
    content = export_to_json(result)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def export_bulk_to_json_file(results: list, filepath: str) -> str:
    """Export multiple results to a JSON file."""
    content = export_bulk_to_json(results)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
