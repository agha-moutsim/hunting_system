"""
Base scraper class — uses Playwright with stealth to bypass bot detection.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth

from config import SCRAPE_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class ScrapedProduct:
    """Standardized product data from any source."""
    source: str
    title: str
    price: float
    url: str
    image_url: Optional[str] = None
    delivery_days_min: Optional[int] = None
    delivery_days_max: Optional[int] = None
    seller: Optional[str] = None
    seller_full_name: Optional[str] = None
    seller_rating: Optional[str] = None
    seller_orders: Optional[str] = None
    store_name: Optional[str] = None
    condition: str = "New"
    verified: bool = True
    raw_html: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)


@dataclass
class DemandData:
    """Sales demand evidence from eBay."""
    sold_count_30d: Optional[int] = None
    sold_count_7d: Optional[int] = None
    last_sale_date: Optional[str] = None
    avg_sold_price: Optional[float] = None
    lowest_sold_price: Optional[float] = None
    highest_sold_price: Optional[float] = None
    verified: bool = True


class BaseScraper(ABC):
    """Base class — Playwright with stealth for bot bypass."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    async def close(self):
        """Close browser and cleanup resources."""
        try:
            if self._page:
                await self._page.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._browser = None
            self._playwright = None

    async def _ensure_browser(self):
        """Lazy-init stealth browser on first use."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = await self._browser.new_context(
                user_agent=SCRAPE_CONFIG["user_agent"],
                locale="en-GB",
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
            )
            self._page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)

    async def fetch(self, url: str, retries: int = 2) -> str:
        """Fetch a URL using stealth Playwright with retry logic."""
        await self._ensure_browser()

        last_error = None
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._page.wait_for_timeout(3000)
                return await self._page.content()
            except Exception as e:
                last_error = e
                if attempt < retries:
                    delay = (attempt + 1) * 2  # 2s, 4s, 6s
                    logger.warning(
                        "Fetch attempt %d/%d failed for %s, retrying in %ds: %s",
                        attempt + 1, retries + 1, url, delay, e
                    )
                    await asyncio.sleep(delay)

        raise last_error

    def parse(self, html: str):
        """Parse HTML into BeautifulSoup."""
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    def _parse_price(self, text: str) -> float:
        """Extract numeric price from text."""
        import re
        match = re.search(r"[\d,.]+", text.replace(",", ""))
        return float(match.group()) if match else 0.0

    @abstractmethod
    async def search(self, query: str) -> list[ScrapedProduct]:
        pass

    @abstractmethod
    async def get_details(self, url: str) -> ScrapedProduct:
        pass

    async def close(self):
        """Close browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
