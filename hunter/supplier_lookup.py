"""Batch supplier lookup — find cheapest supplier price for multiple products."""

import asyncio
from typing import Optional

from hunter.category_scan import CategoryProduct


async def _lookup_single_supplier(product: CategoryProduct) -> Optional[dict]:
    """Look up a single product across all suppliers (parallel)."""
    results = []

    async def _scrape_cj():
        try:
            from scrapers.cjdropshipping import CJDropshippingScraper
            cj = CJDropshippingScraper()
            products = await cj.search(product.title)
            if products:
                return {
                    "name": "CJ Dropshipping",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except Exception:
            pass
        return None

    async def _scrape_ae():
        try:
            from scrapers.aliexpress import AliExpressScraper
            ae = AliExpressScraper()
            products = await ae.search(product.title)
            if products:
                return {
                    "name": "AliExpress",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except Exception:
            pass
        return None

    async def _scrape_amazon():
        try:
            from scrapers.amazon_uk import AmazonUKScraper
            amz = AmazonUKScraper()
            products = await amz.search(product.title)
            if products:
                return {
                    "name": "Amazon UK",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except Exception:
            pass
        return None

    # Run all suppliers in parallel
    try:
        cj_result, ae_result, amz_result = await asyncio.gather(
            _scrape_cj(), _scrape_ae(), _scrape_amazon()
        )
        results = [r for r in [cj_result, ae_result, amz_result] if r is not None]
    except Exception as e:
        print(f"[WARN] Supplier lookup failed: {e}")
        results = []

    # Return cheapest
    if results:
        valid = [r for r in results if r.get("price", 0) > 0]
        if valid:
            return min(valid, key=lambda r: r["price"])

    return None


def batch_supplier_lookup(
    products: list[CategoryProduct],
    progress_callback=None,
) -> list[CategoryProduct]:
    """Find supplier prices for multiple products (parallel)."""

    async def _run_all():
        tasks = [_lookup_single_supplier(p) for p in products]
        return await asyncio.gather(*tasks, return_exceptions=True)

    try:
        loop = asyncio.new_event_loop()
        supplier_results = loop.run_until_complete(_run_all())
        loop.close()
    except Exception as e:
        print(f"[WARN] Batch supplier lookup failed: {e}")
        supplier_results = [None] * len(products)

    # Apply results
    for i, (product, supplier) in enumerate(zip(products, supplier_results)):
        if progress_callback:
            progress_callback(i, len(products), product.title)

        if supplier and not isinstance(supplier, Exception):
            product.supplier_price = supplier.get("price", 0)
            product.supplier_name = supplier.get("name", "")
            product.supplier_url = supplier.get("url", "")

    # Filter: only keep products with supplier price
    return [p for p in products if p.supplier_price > 0]
