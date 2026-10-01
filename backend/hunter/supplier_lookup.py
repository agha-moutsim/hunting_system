"""Batch supplier lookup — find cheapest supplier price for multiple products."""

import asyncio
import time
from typing import Optional

from hunter.category_scan import CategoryProduct
from engine.match import TIER_NO_MATCH, compute_match
from engine.price_gate import in_band
from engine.source_type import supplier_type
from engine.provenance import Provenance

# Timeout per product (seconds)
LOOKUP_TIMEOUT = 15

# eBay listings dropped by the active range gate this run — reported, never silent (PR-4)
_excluded_over_band = 0


def _first_valid(products, reference_title: str = "", ebay_price: float = 0.0):
    """The best supplier row with a usable price that also MATCHED (C14).

    This used to return the first row with a positive price, which meant
    the Hunter could price a product from a listing that merely *sounded*
    similar. Now every candidate is scored against the eBay title by the
    deterministic matcher, rows the matcher rejects are skipped, and the
    best survivor wins — highest match score first, then cheapest.

    No candidate above the threshold returns None: showing no supplier is
    correct, showing the wrong one is not (C12).
    """
    best = None
    best_key = None
    for p in products:
        if not p.price or p.price <= 0:
            continue
        if reference_title:
            r = compute_match(
                reference_title,
                getattr(p, "title", "") or "",
                ebay_price=ebay_price,
                candidate_price=p.price,
            )
            if r.tier == TIER_NO_MATCH:
                continue
            p.match_score = r.score
            p.match_tier = r.tier
            p.match_label = r.label
            p.match_basis = r.reason
            p.match_method = r.method
        else:
            r = None
        key = (-getattr(p, "match_score", 0.0), p.price)
        if best_key is None or key < best_key:
            best, best_key = p, key
    return best


async def _lookup_single_supplier(product: CategoryProduct) -> Optional[dict]:
    """Look up a single product across suppliers with timeout."""
    results = []

    async def _scrape_cj():
        scraper = None
        try:
            from scrapers.cjdropshipping import CJDropshippingScraper
            scraper = CJDropshippingScraper()
            products = await asyncio.wait_for(scraper.search(product.title), timeout=10)
            hit = _first_valid(products, product.title, product.price or 0.0)
            if hit:
                return {
                    "name": "CJ Dropshipping",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 — the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 — derived from the real source, never assumed.
                    "supplier_type": supplier_type(name="CJ Dropshipping", url=hit.url),
                    "provenance": Provenance.VERIFIED.value,
                    "provenance_label": Provenance.VERIFIED.label,
                    "source_url": hit.url,
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
            hit = _first_valid(products, product.title, product.price or 0.0)
            if hit:
                return {
                    "name": "AliExpress",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 — the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 — derived from the real source, never assumed.
                    "supplier_type": supplier_type(name="AliExpress", url=hit.url),
                    "provenance": Provenance.VERIFIED.value,
                    "provenance_label": Provenance.VERIFIED.label,
                    "source_url": hit.url,
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
            hit = _first_valid(products, product.title, product.price or 0.0)
            if hit:
                return {
                    "name": "Amazon UK",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 — the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 — derived from the real source, never assumed.
                    "supplier_type": supplier_type(name="Amazon UK", url=hit.url),
                    "provenance": Provenance.VERIFIED.value,
                    "provenance_label": Provenance.VERIFIED.label,
                    "source_url": hit.url,
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

    # Return cheapest usable supplier price — supplier rows are never
    # range-gated (PR-1); eBay-side rows were already gated above.
    if results:
        valid = [r for r in results if r.get("price", 0) > 0]
        if valid:
            return min(valid, key=lambda r: r["price"])

    return None


def batch_supplier_lookup(
    products: list[CategoryProduct],
    progress_callback=None,
) -> tuple[list[CategoryProduct], int]:
    """Find supplier prices for multiple products (sequential with timeout).

    Returns (in_band_products, excluded_count) — PR-4: the caller must
    report the excluded count, never drop rows silently.
    """
    global _excluded_over_band
    _excluded_over_band = 0

    # Client-supplied products: eBay price must also sit in the band (PR-1)
    kept_products = []
    for p in products:
        if in_band(p.price):
            kept_products.append(p)
        else:
            _excluded_over_band += 1

    # Process ONE product at a time to avoid browser overload
    for i, product in enumerate(kept_products):
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
                # C14 — mirror the matcher's verdict onto the row.
                product.supplier_match_score = supplier.get("match_score", 0.0)
                product.supplier_match_tier = supplier.get("match_tier", "")
                product.supplier_match_label = supplier.get("match_label", "")

        except (asyncio.TimeoutError, Exception) as e:
            print(f"[WARN] Supplier lookup timeout/fail for '{product.title}': {e}")
        finally:
            # Always close the loop
            try:
                if loop and not loop.is_closed():
                    loop.close()
            except:
                pass

    # Filter: keep products with a usable supplier price; eBay listing
    # prices were gated by the active range above (PR-1/PR-4).
    kept = [p for p in kept_products if p.supplier_price > 0]
    return kept, _excluded_over_band
