"""Check prices for tracked products."""

import asyncio
from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import TrackedProduct, PriceHistory
from tracker.alerts import generate_alert
from engine.price_gate import in_band


def check_all_prices(progress_callback=None) -> dict:
    """Check prices for all tracked products."""
    db = SessionLocal()
    try:
        products = db.query(TrackedProduct).filter(TrackedProduct.alert_enabled == True).all()
        results = {"checked": 0, "alerts": 0, "errors": 0, "excluded_over_band": 0}

        for i, product in enumerate(products):
            if progress_callback:
                progress_callback(i, len(products), product.product_name)

            try:
                old_ebay_price = product.ebay_price
                old_supplier_price = product.supplier_price

                # Fetch current prices
                new_ebay_price = _fetch_ebay_price(product.ebay_url)
                new_supplier_price = product.supplier_price  # Keep existing for now

                # PR-6: out-of-band figures are never stored (write-time gate)
                if new_ebay_price > 0 and not in_band(new_ebay_price):
                    results["excluded_over_band"] += 1
                    new_ebay_price = 0.0

                if new_ebay_price > 0:
                    product.ebay_price = new_ebay_price

                product.supplier_price = new_supplier_price
                product.last_checked = datetime.utcnow()

                # Record price history (band-filtered figure only — PR-6)
                if new_ebay_price > 0:
                    history = PriceHistory(
                        tracked_product_id=product.id,
                        ebay_price=new_ebay_price,
                        supplier_price=new_supplier_price,
                    )
                    db.add(history)

                # Generate alert if price changed significantly
                if old_ebay_price > 0 and new_ebay_price > 0:
                    price_change = new_ebay_price - old_ebay_price
                    if abs(price_change) >= 0.50:  # Alert if changed by £0.50+
                        alert = generate_alert(
                            product,
                            "price_drop" if price_change < 0 else "price_increase",
                            old_ebay_price,
                            new_ebay_price,
                        )
                        if alert:
                            results["alerts"] += 1

                results["checked"] += 1

            except Exception as e:
                print(f"[WARN] Price check failed for '{product.product_name}': {e}")
                results["errors"] += 1

        db.commit()
        return results

    except Exception as e:
        print(f"[ERROR] Batch price check failed: {e}")
        db.rollback()
        return {"checked": 0, "alerts": 0, "errors": 0}
    finally:
        db.close()


def check_single_price(tracked_id: int) -> Optional[float]:
    """Check price for a single tracked product."""
    db = SessionLocal()
    try:
        product = db.query(TrackedProduct).filter(TrackedProduct.id == tracked_id).first()
        if not product:
            return None

        old_price = product.ebay_price
        new_price = _fetch_ebay_price(product.ebay_url)

        # PR-6 write gate: out-of-band figures are never stored
        if new_price > 0 and not in_band(new_price):
            print(
                f"[BAND] '{product.product_name}' new price £{new_price:.2f} "
                "outside band — not stored"
            )
            return None

        if new_price > 0:
            product.ebay_price = new_price
            product.last_checked = datetime.utcnow()

            # Record history
            history = PriceHistory(
                tracked_product_id=product.id,
                ebay_price=new_price,
                supplier_price=product.supplier_price,
            )
            db.add(history)

            # Generate alert if changed
            if old_price > 0 and abs(new_price - old_price) >= 0.50:
                generate_alert(
                    product,
                    "price_drop" if new_price < old_price else "price_increase",
                    old_price,
                    new_price,
                )

            db.commit()
            return new_price

        return None

    except Exception as e:
        print(f"[ERROR] Single price check failed: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def _fetch_ebay_price(url: str) -> float:
    """Fetch current eBay price from a listing URL."""
    try:
        import requests
        from bs4 import BeautifulSoup
        from config import SCRAPE_CONFIG

        session = requests.Session()
        session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
        })

        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to find price
        price_el = soup.select_one("span.ux-textspans--BOLD") or soup.select_one("span[class*='price']")
        if price_el:
            import re
            price_text = price_el.get_text(strip=True).replace(",", "")
            match = re.search(r"[\d.]+", price_text)
            if match:
                return float(match.group())

        return 0.0

    except Exception as e:
        print(f"[WARN] Failed to fetch eBay price: {e}")
        return 0.0
