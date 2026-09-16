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
        """Get batch analysis summary."""
        successful = [r for r in results if r.status == "success"]
        failed = [r for r in results if r.status == "error"]

        profitable = []
        for r in successful:
            if r.result and r.result.get("verdict"):
                verdict = r.result["verdict"]
                if hasattr(verdict, "profit") and verdict.profit > 0:
                    profitable.append(r)

        return {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "profitable": len(profitable),
            "products": [
                {
                    "query": r.query,
                    "verdict": getattr(r.result.get("verdict"), "verdict", "N/A") if r.result else "N/A",
                    "profit": getattr(r.result.get("verdict"), "profit", 0) if r.result else 0,
                }
                for r in successful
            ],
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
            icon = "✓" if profit > 0 else "✗"
            lines.append(f"  {icon} {p['query'][:40]} — {verdict} (£{profit:.2f})")

        lines.append("")
        return "\n".join(lines)
