"""
Scraper health check — test each supplier scraper individually.

Usage:
    python -m utils.health_check
    python -m utils.health_check --scraper aliexpress
"""

import asyncio
import time
from dataclasses import dataclass

from scrapers.aliexpress import AliExpressScraper
from scrapers.amazon_uk import AmazonUKScraper
from scrapers.bandq import BandQScraper
from scrapers.cjdropshipping import CJDropshippingScraper
from scrapers.godropship import GoDropshipScraper
from scrapers.joybuy import JoybuyScraper
from scrapers.toolstation import ToolstationScraper
from scrapers.ebay import EbayScraper


@dataclass
class HealthResult:
    name: str
    status: str  # "ok", "error", "blocked"
    message: str
    response_time: float
    products_found: int


SCRAPERS = {
    "ebay": EbayScraper,
    "aliexpress": AliExpressScraper,
    "amazon_uk": AmazonUKScraper,
    "cjdropshipping": CJDropshippingScraper,
    "godropship": GoDropshipScraper,
    "joybuy": JoybuyScraper,
    "bandq": BandQScraper,
    "toolstation": ToolstationScraper,
}

TEST_QUERY = "wireless earbuds"


async def check_scraper(name: str, scraper_class) -> HealthResult:
    """Test a single scraper with a query."""
    start = time.time()
    scraper = scraper_class()

    try:
        search_result = scraper.search(TEST_QUERY)
        if asyncio.iscoroutine(search_result):
            search_result = await search_result
        results = search_result
        elapsed = time.time() - start

        if results:
            return HealthResult(
                name=name,
                status="ok",
                message=f"Found {len(results)} products",
                response_time=round(elapsed, 2),
                products_found=len(results),
            )
        else:
            return HealthResult(
                name=name,
                status="empty",
                message="No results returned (may need API keys)",
                response_time=round(elapsed, 2),
                products_found=0,
            )
    except Exception as e:
        elapsed = time.time() - start
        error_msg = str(e)
        status = "blocked" if "403" in error_msg or "Forbidden" in error_msg else "error"

        return HealthResult(
            name=name,
            status=status,
            message=error_msg[:100],
            response_time=round(elapsed, 2),
            products_found=0,
        )
    finally:
        close_result = scraper.close()
        if asyncio.iscoroutine(close_result):
            await close_result


async def run_health_check(scraper_name: str = None) -> list[HealthResult]:
    """Run health check on all or one scraper."""
    if scraper_name:
        if scraper_name not in SCRAPERS:
            return [HealthResult(
                name=scraper_name,
                status="error",
                message=f"Unknown scraper: {scraper_name}",
                response_time=0,
                products_found=0,
            )]
        result = await check_scraper(scraper_name, SCRAPERS[scraper_name])
        return [result]

    tasks = [
        check_scraper(name, cls)
        for name, cls in SCRAPERS.items()
    ]
    return await asyncio.gather(*tasks)


def format_results(results: list[HealthResult]) -> str:
    """Format health check results for display."""
    lines = ["\nScraper Health Check Results:\n"]
    lines.append(f"{'Scraper':<15} {'Status':<10} {'Time':<8} {'Products':<10} Message")
    lines.append("-" * 75)

    for r in results:
        status_icon = {
            "ok": "✓ OK",
            "empty": "- EMPTY",
            "error": "✗ ERROR",
            "blocked": "✗ BLOCKED",
        }.get(r.status, r.status)

        lines.append(
            f"{r.name:<15} {status_icon:<10} {r.response_time:<8}s "
            f"{r.products_found:<10} {r.message[:40]}"
        )

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else None
    results = asyncio.run(run_health_check(name))
    print(format_results(results))
