"""Batch demand checking — verify sold counts for multiple products."""

from typing import Optional

from hunter.category_scan import CategoryProduct


def batch_demand_check(
    products: list[CategoryProduct],
    min_sold_30d: Optional[int] = None,
    min_sold_7d: Optional[int] = None,
    progress_callback=None,
    marketplace: str = "EBAY_GB",
) -> list[CategoryProduct]:
    """Check demand (sold counts) for multiple products.

    Thresholds default to the config rules (>=30/30d, >=8/7d — C4); a
    caller may override per scan. An UNKNOWN 7-day figure (None) never
    prunes a product — the verdict engine holds it at PENDING instead
    (C4: never assume).
    """
    from config import FILTERS
    from engine.stores import resolve_stores
    from marketplaces import get_marketplace, market_filter_defaults
    from scrapers.ebay_sold import EbaySoldScraper

    market = get_marketplace(marketplace)
    if min_sold_30d is None:
        if market["id"] == "EBAY_GB":
            min_sold_30d = FILTERS["demand_min_30d"]
        else:
            min_sold_30d = market_filter_defaults(market).get(
                "demand_min_30d", FILTERS["demand_min_30d"]
            )
    if min_sold_7d is None:
        if market["id"] == "EBAY_GB":
            min_sold_7d = FILTERS["demand_min_7d"]
        else:
            min_sold_7d = market_filter_defaults(market).get(
                "demand_min_7d", FILTERS["demand_min_7d"]
            )

    scraper = EbaySoldScraper(marketplace)
    results = []

    for i, product in enumerate(products):
        if progress_callback:
            progress_callback(i, len(products), product.title)

        try:
            sold_data = scraper.get_sold_data(product.title)
            # Observed SALES only. None means "not measured", which is the
            # normal case: this app has no sold-listing search (see
            # scrapers/base.py DemandData).
            product.sold_30d = sold_data.total_sold_30d
            product.sold_7d = sold_data.total_sold_7d  # None = unknown
            # In-band New ACTIVE listings: SUPPLY. Carried under its own name
            # so nothing downstream can read it as demand.
            product.active_listings_in_band = sold_data.active_listings_in_band

            # C11 — this query already listed the sellers it saw; keep them
            # instead of paying for a second store-discovery request.
            # Empty sold_data ⇒ [] (never padded to 4).
            try:
                product.ebay_stores = resolve_stores(
                    sold_data=sold_data, marketplace=marketplace
                )
            except Exception as e:
                print(f"[WARN] Store build failed for '{product.title}': {e}")
                product.ebay_stores = []

            seven_day_ok = (
                product.sold_7d is None or product.sold_7d >= min_sold_7d
            )
            # What this gate can actually measure. eBay exposes no sold
            # search, so real sales are usually absent and the only figure
            # available is the competing New listing count. The `min_sold_*`
            # argument names predate that finding: the number compared here
            # is LISTINGS, and an unknown never prunes a row (C4).
            observed = (
                product.sold_30d
                if product.sold_30d is not None
                else product.active_listings_in_band
            )
            if observed is None:
                results.append(product)
            elif observed >= min_sold_30d and seven_day_ok:
                results.append(product)

        except Exception as e:
            print(f"[WARN] Demand check failed for '{product.title}': {e}")
            # Keep product even if check fails (will be filtered later)
            results.append(product)

    return results
