"""
Batch analysis — analyze multiple products at once.

Usage:
    from batch import BatchAnalyzer
    analyzer = BatchAnalyzer()
    results = analyzer.analyze_batch(["wireless earbuds", "usb charger"])
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from pipeline import Pipeline

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    query: str
    status: str  # "success", "error", "skipped"
    result: Optional[dict] = None
    error: Optional[str] = None


class BatchAnalyzer:
    """Analyze multiple products in sequence."""

    def __init__(self, max_products: int = 10):
        self.max_products = max_products
        self.pipeline = Pipeline()

    async def analyze_batch(
        self,
        queries: list[str],
        progress_callback=None,
    ) -> list[BatchResult]:
        """Analyze a list of queries."""
        results = []

        for i, query in enumerate(queries[:self.max_products]):
            if progress_callback:
                progress_callback(i + 1, len(queries), query)

            try:
                result = await self.pipeline.run(query)
                results.append(BatchResult(
                    query=query,
                    status="success",
                    result=result,
                ))
            except Exception as e:
                logger.exception("Batch analysis failed for: %s", query)
                results.append(BatchResult(
                    query=query,
                    status="error",
                    error=str(e),
                ))

        return results

    def analyze_batch_sync(
        self,
        queries: list[str],
        progress_callback=None,
    ) -> list[BatchResult]:
        """Synchronous wrapper for batch analysis."""
        return asyncio.run(self.analyze_batch(queries, progress_callback))

    def get_summary(self, results: list[BatchResult]) -> dict:
        """Get batch analysis summary.

        The pipeline returns its verdict as a DICT, so the old `getattr(...,
        "profit", 0)` read a default on every row: profit was always 0 and the
        verdict always "N/A". A figure is reported only when the pipeline
        stamped it computed; `profit_computed: False` is authoritative even if
        a stale number sits beside it.
        """
        successful = [r for r in results if r.status == "success"]
        failed = [r for r in results if r.status == "error"]

        profitable = []
        products = []
        for r in successful:
            verdict = (r.result or {}).get("verdict")
            if not isinstance(verdict, dict):
                verdict = {}
            computed = verdict.get("profit_computed")
            profit = verdict.get("profit")
            if computed is None:
                # A result shaped before the flag existed: a non-zero figure
                # can only have come from a calculation.
                computed = isinstance(profit, (int, float)) and profit != 0
            measured = profit if computed and isinstance(profit, (int, float)) else None
            if measured is not None and measured > 0:
                profitable.append(r)
            products.append({
                "query": r.query,
                "verdict": verdict.get("verdict") or "N/A",
                "profit": measured,
            })

        return {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "profitable": len(profitable),
            "products": products,
        }

    def format_summary(self, results: list[BatchResult]) -> str:
        """Format batch summary for display."""
        summary = self.get_summary(results)

        lines = [
            f"\nBatch Analysis Summary:",
            f"  Total: {summary['total']}",
            f"  Successful: {summary['successful']}",
            f"  Failed: {summary['failed']}",
            f"  Profitable: {summary['profitable']}",
            "\nResults:",
        ]

        for p in summary["products"]:
            verdict = p["verdict"]
            profit = p["profit"]
            if profit is None:
                icon = "·"
                money = " (profit not computed)"
            else:
                icon = "✓" if profit > 0 else "✗"
                money = f" (£{profit:.2f})"
            lines.append(f"  {icon} {p['query'][:40]} — {verdict}{money}")

        lines.append("")
        return "\n".join(lines)
