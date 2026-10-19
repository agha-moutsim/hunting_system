"""Check prices for tracked products."""

import asyncio
from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import TrackedProduct, PriceHistory
from hunter.alerts import generate_for_product


def check_all_prices(progress_callback=None) -> dict:
    """Check prices for all tracked products."""
    db = SessionLocal()
    try:
        products = db.query(TrackedProduct).filter(TrackedProduct.alert_enabled == True).all()
        results = {"checked": 0, "alerts": 0, "errors": 0}
        recorded: list[int] = []

        for i, product in enumerate(products):
            if progress_callback:
                progress_callback(i, len(products), product.product_name)

            try:
                new_ebay_price = _fetch_ebay_price(product.ebay_url)
                new_supplier_price = product.supplier_price  # Keep existing for now

                if new_ebay_price > 0:
                    product.ebay_price = new_ebay_price

                product.supplier_price = new_supplier_price
                product.last_checked = datetime.utcnow()

                if new_ebay_price > 0:
                    history = PriceHistory(
                        tracked_product_id=product.id,
                        ebay_price=new_ebay_price,
                        supplier_price=new_supplier_price,
                    )
                    db.add(history)
                    recorded.append(product.id)

                results["checked"] += 1

            except Exception as e:
                print(f"[WARN] Price check failed for '{product.product_name}': {e}")
                results["errors"] += 1

        db.commit()

        # The alerts come from the one rule in hunter.alerts - the same code
        # the scheduled pass runs - applied to the readings this check just
        # stored. An earlier writer here had its own 50p threshold and its own
        # message format in tracker/alerts.py; a second opinion is how two
        # inboxes start disagreeing about one price.
        for product_id in recorded:
            results["alerts"] += generate_for_product(product_id)["written"]

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

        new_price = _fetch_ebay_price(product.ebay_url)

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

            db.commit()

            # One event, one row: the alert comes from the same rule the
            # scheduled pass uses (hunter.alerts), applied to the reading
            # just stored.
            generate_for_product(product.id)

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
