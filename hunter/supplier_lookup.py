"""Batch supplier lookup — find cheapest supplier price for multiple products."""

import asyncio
import time
from typing import Optional

from hunter.category_scan import CategoryProduct

# Timeout per product (seconds)
LOOKUP_TIMEOUT = 15


async def _lookup_single_supplier(product: CategoryProduct) -> Optional[dict]:
    """Look up a single product across suppliers with timeout."""
    results = []

    async def _scrape_cj():
        scraper = None
        try:
            from scrapers.cjdropshipping import CJDropshippingScraper
            scraper = CJDropshippingScraper()
            products = await asyncio.wait_for(scraper.search(product.title), timeout=10)
            if products:
                return {
                    "name": "CJ Dropshipping",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except (asyncio.TimeoutError, Exception):
            pass
        finally:
            if scraper and hasattr(scraper, 'close'):
                try:
                    await scraper.close()
                except:
                    pass
        return None

    async def _scrape_ae():
        scraper = None
        try:
            from scrapers.aliexpress import AliExpressScraper
            scraper = AliExpressScraper()
            products = await asyncio.wait_for(scraper.search(product.title), timeout=10)
            if products:
                return {
                    "name": "AliExpress",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except (asyncio.TimeoutError, Exception):
            pass
        finally:
            if scraper and hasattr(scraper, 'close'):
                try:
                    await scraper.close()
                except:
                    pass
        return None

    async def _scrape_amazon():
        scraper = None
        try:
            from scrapers.amazon_uk import AmazonUKScraper
            scraper = AmazonUKScraper()
            products = await asyncio.wait_for(scraper.search(product.title), timeout=10)
            if products:
                return {
                    "name": "Amazon UK",
                    "price": products[0].price,
                    "url": products[0].url,
                    "delivery_days": f"{products[0].delivery_days_min}-{products[0].delivery_days_max}",
                }
        except (asyncio.TimeoutError, Exception):
            pass
        finally:
            if scraper and hasattr(scraper, 'close'):
                try:
                    await scraper.close()
                except:
                    pass
        return None

    # Run CJ first (fastest - API), then others if needed
    try:
        cj_result = await _scrape_cj()
        if cj_result:
            results.append(cj_result)
    except Exception:
        pass

    # Only run other suppliers if CJ didn't find anything
    if not results:
        try:
            ae_result, amz_result = await asyncio.gather(
                _scrape_ae(), _scrape_amazon()
            )
            results = [r for r in [ae_result, amz_result] if r is not None]
        except Exception:
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
    """Find supplier prices for multiple products (sequential with timeout)."""

    # Process ONE product at a time to avoid browser overload
    for i, product in enumerate(products):
        if progress_callback:
            progress_callback(i, len(products), product.title)

        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Add timeout for each product
            supplier = loop.run_until_complete(
                asyncio.wait_for(_lookup_single_supplier(product), timeout=LOOKUP_TIMEOUT)
            )

            if supplier and not isinstance(supplier, Exception):
                product.supplier_price = supplier.get("price", 0)
                product.supplier_name = supplier.get("name", "")
                product.supplier_url = supplier.get("url", "")

        except (asyncio.TimeoutError, Exception) as e:
            print(f"[WARN] Supplier lookup timeout/fail for '{product.title}': {e}")
        finally:
            # Always close the loop
            try:
                if loop and not loop.is_closed():
                    loop.close()
            except:
                pass

    # Filter: only keep products with supplier price
    return [p for p in products if p.supplier_price > 0]
