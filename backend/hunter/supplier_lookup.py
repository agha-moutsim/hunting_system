"""Batch supplier lookup -------- find cheapest supplier price for multiple products."""

import asyncio
import time
from typing import Optional

from hunter.category_scan import CategoryProduct
from engine.match import TIER_NO_MATCH, compute_match, image_hash_for
from engine.price_gate import in_band
from engine.source_type import supplier_type
from engine.provenance import Provenance

# Timeout for ONE supplier fetch inside a product lookup (seconds).
SUPPLIER_FETCH_TIMEOUT = 10

# Timeout per product (seconds).
#
# REGRESSION-003: this was 15 while the work inside it could take 20 - CJ for
# SUPPLIER_FETCH_TIMEOUT, then, when it found nothing, an AliExpress/Amazon
# gather costing another SUPPLIER_FETCH_TIMEOUT. The outer kill therefore
# fired before its own body finished, `supplier` came back None, and every
# remaining product vanished with no explanation. The budget now covers the
# worst case it actually contains.
LOOKUP_TIMEOUT = SUPPLIER_FETCH_TIMEOUT * 2 + 5

# eBay listings dropped by the active range gate this run -------- reported, never silent (PR-4)
_excluded_over_band = 0


def _first_valid(
    products,
    reference_title: str = "",
    ebay_price: float = 0.0,
    ebay_image_hash: int | None = None,
):
    """The best supplier row with a usable price that also MATCHED (C14).

    This used to return the first row with a positive price, which meant
    the Hunter could price a product from a listing that merely *sounded*
    similar. Now every candidate is scored against the eBay title by the
    deterministic matcher, rows the matcher rejects are skipped, and the
    best survivor wins -------- highest match score first, then cheapest.

    No candidate above the threshold returns None: showing no supplier is
    correct, showing the wrong one is not (C12).

    `ebay_image_hash` turns on C14's image phash. It only ever fires when
    both sides have an image; with no reference hash nothing is downloaded,
    and an image that cannot be read stays unknown rather than guessed.
    """
    best = None
    best_key = None
    for p in products:
        if not p.price or p.price <= 0:
            continue
        if reference_title:
            if ebay_image_hash is not None and getattr(p, "image_hash", None) is None:
                p.image_hash = image_hash_for(getattr(p, "image_url", None))
            r = compute_match(
                reference_title,
                getattr(p, "title", "") or "",
                ebay_price=ebay_price,
                candidate_price=p.price,
                ebay_image_hash=ebay_image_hash,
                candidate_image_hash=getattr(p, "image_hash", None),
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
    """Find the cheapest *genuinely matching* supplier offer for one product.

    REGRESSION-002: this used to lead with CJ/Aliexpress/Amazon, whose
    responses are mostly not the same product -------- 60 of the 109 supplier rows
    in the real database were e.g. GBP35.99 earbuds matched to a GBP641.48
    AliExpress row. The matcher correctly rejected them, so the Hunter showed
    nothing at all. Discovery (SerpApi Google Shopping) is tried FIRST because
    it returns real product URLs for offers that actually match; the three
    direct scrapers remain as the fallback.

    The matcher still decides: a bad offer from a good source is dropped
    exactly as before (C14).
    """
    results = []

    async def _scrape_discovery():
        """SerpApi Google Shopping -------- the primary source.

        Runs in a thread because `discover` is blocking HTTP, and must never
        hold the event loop the fallback scrapers share.
        """
        try:
            from scrapers.serpapi_discovery import discover
            rows = await asyncio.to_thread(discover, product.title)
        except Exception as e:
            print(f"[WARN] Supplier discovery failed: {e}")
            return None
        if not rows:
            return None

        hit = _first_valid(
            rows, product.title, product.price or 0.0,
            image_hash_for(getattr(product, "image_url", None)),
        )
        if not hit:
            return None  # offers existed, none cleared C14 -> not a match
        return {
            "name": hit.source,
            "price": hit.price,
            "url": hit.url,
            "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
            "product_title": getattr(hit, "title", ""),
            "match_score": getattr(hit, "match_score", 0.0),
            "match_tier": getattr(hit, "match_tier", ""),
            "match_label": getattr(hit, "match_label", ""),
            "supplier_type": supplier_type(name=hit.source, url=hit.url),
            # C13 -------- read off a real listing, so verified; and the source's own
            # stock/shipping words travel with the row rather than assumptions.
            "provenance": Provenance.VERIFIED.value,
            "provenance_label": Provenance.VERIFIED.label,
            "source_url": hit.url,
            "in_stock": getattr(hit, "in_stock", ""),
            "stock_raw": getattr(hit, "stock_raw", ""),
            "shipping_cost": getattr(hit, "shipping_cost", 0.0),
            "shipping_days": getattr(hit, "shipping_days", 0),
            "shipping_raw": getattr(hit, "shipping_raw", ""),
            "found_via": "discovery",
        }

    async def _scrape_cj():
        scraper = None
        try:
            from scrapers.cjdropshipping import CJDropshippingScraper
            scraper = CJDropshippingScraper()
            products = await asyncio.wait_for(scraper.search(product.title), timeout=10)
            hit = _first_valid(
                products, product.title, product.price or 0.0,
                image_hash_for(getattr(product, "image_url", None)),
            )
            if hit:
                return {
                    "name": "CJ Dropshipping",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 -------- the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 -------- derived from the real source, never assumed.
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
            hit = _first_valid(
                products, product.title, product.price or 0.0,
                image_hash_for(getattr(product, "image_url", None)),
            )
            if hit:
                return {
                    "name": "AliExpress",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 -------- the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 -------- derived from the real source, never assumed.
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
            hit = _first_valid(
                products, product.title, product.price or 0.0,
                image_hash_for(getattr(product, "image_url", None)),
            )
            if hit:
                return {
                    "name": "Amazon UK",
                    "price": hit.price,
                    "url": hit.url,
                    "delivery_days": f"{hit.delivery_days_min}-{hit.delivery_days_max}",
                    "product_title": getattr(hit, "title", ""),
                    # C14 -------- the computed score travels with the row so the
                    # report and the API say what the matcher decided.
                    "match_score": getattr(hit, "match_score", 0.0),
                    "match_tier": getattr(hit, "match_tier", ""),
                    "match_label": getattr(hit, "match_label", ""),
                    # C13 -------- derived from the real source, never assumed.
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

    # Discovery first (REGRESSION-002), then CJ, then the rest only if
    # nothing was found -------- a cheaper confirmed offer is still preferred.
    try:
        discovery_result = await _scrape_discovery()
        if discovery_result:
            results.append(discovery_result)
    except Exception:
        pass

    # Run CJ next (fastest - API), then others if needed
    try:
        cj_result = await _scrape_cj()
        if cj_result:
            results.append(cj_result)
    except Exception:
        pass

    # Only run the remaining suppliers if nothing was found
    if not results:
        try:
            ae_result, amz_result = await asyncio.gather(
                _scrape_ae(), _scrape_amazon()
            )
            results = [r for r in [ae_result, amz_result] if r is not None]
        except Exception:
            results = []

    # Return cheapest usable supplier price -------- supplier rows are never
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

    Returns (products, excluded_count) -------- PR-4: the caller must report the
    excluded count, never drop rows silently.

    REGRESSION-003/004: a product that yielded no supplier is KEPT and marked
    `supplier_status`, rather than vanishing. The old code filtered it away
    with `if p.supplier_price > 0`, so a run where every lookup timed out
    returned an empty list and the page showed "no products" as though the
    category were empty. Only an out-of-band eBay price removes a row, and
    that count is already reported.
    """
    global _excluded_over_band
    _excluded_over_band = 0

    # Client-supplied products: eBay price must also sit in the band (PR-1)
    kept_products = []
    for p in products:
        if in_band(p.price):
            p.supplier_status = ""
            kept_products.append(p)
        else:
            p.supplier_status = "out_of_band"
            p.supplier_status_reason = (
                f"eBay price GBP{p.price:.2f} is outside the active range"
            )
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
                # C14 -------- mirror the matcher's verdict onto the row.
                product.supplier_match_score = supplier.get("match_score", 0.0)
                product.supplier_match_tier = supplier.get("match_tier", "")
                product.supplier_match_label = supplier.get("match_label", "")
                product.supplier_status = "found"
                product.supplier_status_reason = (
                    f"{supplier.get('name', 'supplier')} at "
                    f"GBP{supplier.get('price', 0):.2f}"
                )
                # C13 - the source's own shipping words. 0.0 means "not
                # stated", which profit treats as an incomplete figure rather
                # than as free postage.
                product.shipping_cost = supplier.get("shipping_cost", 0.0) or 0.0
                product.shipping_raw = supplier.get("shipping_raw", "") or ""
            else:
                product.supplier_status = "no_supplier"
                product.supplier_status_reason = (
                    "no approved supplier returned a matching offer"
                )

        except (asyncio.TimeoutError, Exception) as e:
            # REGRESSION-003 -------- a timeout is a reason, not a deletion.
            product.supplier_status = "timeout"
            product.supplier_status_reason = (
                f"supplier lookup timed out after {LOOKUP_TIMEOUT}s"
            )
            print(f"[WARN] Supplier lookup timeout/fail for '{product.title}': {e}")
        finally:
            # Always close the loop
            try:
                if loop and not loop.is_closed():
                    loop.close()
            except Exception:
                pass

    # REGRESSION-004: rows with no supplier price are RETURNED and marked, not
    # dropped. Only the out-of-band rows above left the list, and they are
    # counted. Dropping here is what made a fully-timed-out run look like an
    # empty category.
    return kept_products, _excluded_over_band
