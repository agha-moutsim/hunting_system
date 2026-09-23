"""
Export functionality — save analysis results to CSV/JSON.

Usage:
    from export import export_to_csv, export_to_json
    export_to_csv(results, "output.csv")
    export_to_json(results, "output.json")
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def export_to_csv(results: dict[str, Any], filepath: str) -> str:
    """Export analysis results to CSV file."""
    row = {
        "timestamp": datetime.now().isoformat(),
        "title": results.get("ebay_product", {}).get("title", ""),
        "ebay_price": results.get("ebay_product", {}).get("price", 0),
        "condition": results.get("ebay_product", {}).get("condition", ""),
        "sold_30d": results.get("demand", {}).get("sold_count_30d", 0),
        "sold_7d": results.get("demand", {}).get("sold_count_7d", 0),
        "avg_sold_price": results.get("demand", {}).get("avg_sold_price", 0),
        "best_supplier": "",
        "best_supplier_price": 0,
        "profit": 0,
        "margin": 0,
        "verdict": "",
        "brand_verdict": "",
        "demand_assessment": "",
        "errors": "; ".join(results.get("errors", [])),
    }

    # Find best supplier
    suppliers = results.get("supplier_matches", [])
    if suppliers:
        best = min(suppliers, key=lambda s: s.get("price", float("inf")))
        row["best_supplier"] = best.get("source", "")
        row["best_supplier_price"] = best.get("price", 0)

    # Get verdict
    verdict = results.get("verdict")
    if verdict:
        row["profit"] = getattr(verdict, "profit", 0)
        row["margin"] = getattr(verdict, "margin", 0)
        row["verdict"] = getattr(verdict, "verdict", "")

    # Get LLM analysis
    llm = results.get("llm_analysis")
    if llm:
        row["brand_verdict"] = getattr(llm, "brand_verdict", "")
        row["demand_assessment"] = getattr(llm, "demand_assessment", "")

    # Append to CSV (create with headers if new)
    path = Path(filepath)
    file_exists = path.exists()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return filepath


def export_to_json(results: dict[str, Any], filepath: str) -> str:
    """Export analysis results to JSON file."""
    # Convert dataclasses to dicts
    export_data = {
        "timestamp": datetime.now().isoformat(),
        "product": results.get("ebay_product"),
        "demand": results.get("demand"),
        "suppliers": results.get("supplier_matches"),
        "llm_analysis": results.get("llm_analysis"),
        "verdict": results.get("verdict"),
        "scorecard": results.get("scorecard"),
        "errors": results.get("errors"),
    }

    # Handle non-serializable objects
    def serialize(obj):
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return str(obj)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, default=serialize)

    return filepath


def export_batch_csv(batch_results: list[dict], filepath: str) -> str:
    """Export multiple analysis results to CSV."""
    if not batch_results:
        return filepath

    rows = []
    for results in batch_results:
        row = {
            "timestamp": datetime.now().isoformat(),
            "title": results.get("ebay_product", {}).get("title", ""),
            "ebay_price": results.get("ebay_product", {}).get("price", 0),
            "verdict": "",
            "profit": 0,
        }
        verdict = results.get("verdict")
        if verdict:
            row["profit"] = getattr(verdict, "profit", 0)
            row["verdict"] = getattr(verdict, "verdict", "")
        rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return filepath
