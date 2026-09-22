"""Batch demand checking — verify sold counts for multiple products."""

from typing import Optional

from hunter.category_scan import CategoryProduct


def batch_demand_check(
    products: list[CategoryProduct],
    min_sold_30d: int = 10,
    min_sold_7d: int = 1,
    progress_callback=None,
) -> list[CategoryProduct]:
    """Check demand (sold counts) for multiple products.
    
    Filters out products that don't meet minimum demand thresholds.
    """
    from scrapers.ebay_sold import EbaySoldScraper

    scraper = EbaySoldScraper()
    results = []

    for i, product in enumerate(products):
        if progress_callback:
            progress_callback(i, len(products), product.title)

        try:
            sold_data = scraper.get_sold_data(product.title)
            product.sold_30d = sold_data.total_sold_30d
            product.sold_7d = sold_data.total_sold_7d

            # Apply demand filters
            if product.sold_30d >= min_sold_30d and product.sold_7d >= min_sold_7d:
                results.append(product)

        except Exception as e:
            print(f"[WARN] Demand check failed for '{product.title}': {e}")
            # Keep product even if check fails (will be filtered later)
            results.append(product)

    return results
