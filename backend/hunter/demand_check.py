"""Batch demand checking — verify sold counts for multiple products."""

from typing import Optional

from hunter.category_scan import CategoryProduct


def batch_demand_check(
    products: list[CategoryProduct],
    min_sold_30d: Optional[int] = None,
    min_sold_7d: Optional[int] = None,
    progress_callback=None,
) -> list[CategoryProduct]:
    """Check demand (sold counts) for multiple products.

    Thresholds default to the config rules (>=30/30d, >=8/7d — C4); a
    caller may override per scan. An UNKNOWN 7-day figure (None) never
    prunes a product — the verdict engine holds it at PENDING instead
    (C4: never assume).
    """
    from config import FILTERS
    from scrapers.ebay_sold import EbaySoldScraper

    if min_sold_30d is None:
        min_sold_30d = FILTERS["demand_min_30d"]
    if min_sold_7d is None:
        min_sold_7d = FILTERS["demand_min_7d"]

    scraper = EbaySoldScraper()
    results = []

    for i, product in enumerate(products):
        if progress_callback:
            progress_callback(i, len(products), product.title)

        try:
            sold_data = scraper.get_sold_data(product.title)
            product.sold_30d = sold_data.total_sold_30d
            product.sold_7d = sold_data.total_sold_7d  # None = unknown

            seven_day_ok = (
                product.sold_7d is None or product.sold_7d >= min_sold_7d
            )
            if product.sold_30d >= min_sold_30d and seven_day_ok:
                results.append(product)

        except Exception as e:
            print(f"[WARN] Demand check failed for '{product.title}': {e}")
            # Keep product even if check fails (will be filtered later)
            results.append(product)

    return results
