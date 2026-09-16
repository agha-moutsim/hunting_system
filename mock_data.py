"""
Mock data for testing without API access.

Usage:
    Set MOCK_MODE=true in .env to use mock data instead of live scraping.
"""

from scrapers.base import ScrapedProduct, DemandData


MOCK_EBAY_PRODUCTS = [
    ScrapedProduct(
        source="ebay_uk",
        title="Wireless Bluetooth Earbuds TWS 5.0 Headphones Sport Gym",
        price=12.99,
        url="https://www.ebay.co.uk/itm/123456789",
        image_url="https://i.ebayimg.com/images/g/mock1.jpg",
        seller="tech_deals_uk",
        condition="New",
        delivery_days_min=1,
        delivery_days_max=3,
        verified=True,
    ),
    ScrapedProduct(
        source="ebay_uk",
        title="USB C Fast Charger 20W Wall Plug UK Mains Adapter",
        price=8.49,
        url="https://www.ebay.co.uk/itm/987654321",
        image_url="https://i.ebayimg.com/images/g/mock2.jpg",
        seller="gadget_world",
        condition="New",
        delivery_days_min=1,
        delivery_days_max=2,
        verified=True,
    ),
    ScrapedProduct(
        source="ebay_uk",
        title="LED Desk Lamp Dimmable Touch Control USB Charging Port",
        price=18.99,
        url="https://www.ebay.co.uk/itm/456789123",
        image_url="https://i.ebayimg.com/images/g/mock3.jpg",
        seller="home_electrics",
        condition="New",
        delivery_days_min=2,
        delivery_days_max=4,
        verified=True,
    ),
]

MOCK_DEMAND = DemandData(
    sold_count_30d=25,
    sold_count_7d=8,
    avg_sold_price=13.50,
    lowest_sold_price=9.99,
    highest_sold_price=18.99,
    verified=True,
)

MOCK_SUPPLIERS = {
    "aliexpress": [
        ScrapedProduct(
            source="aliexpress",
            title="TWS Wireless Bluetooth 5.0 Earbuds Sport Headphones",
            price=3.20,
            url="https://aliexpress.com/item/111222.html",
            delivery_days_min=12,
            delivery_days_max=25,
            verified=True,
        ),
    ],
    "amazon_uk": [
        ScrapedProduct(
            source="amazon_uk",
            title="Wireless Bluetooth Earbuds TWS 5.0",
            price=9.99,
            url="https://amazon.co.uk/dp/B0Mock1",
            delivery_days_min=1,
            delivery_days_max=3,
            verified=True,
        ),
    ],
    "cjdropshipping": [
        ScrapedProduct(
            source="cjdropshipping",
            title="TWS 5.0 Bluetooth Wireless Earbuds",
            price=4.50,
            url="https://cjdropshipping.com/product/123",
            delivery_days_min=7,
            delivery_days_max=20,
            verified=True,
        ),
    ],
    "godropship": [
        ScrapedProduct(
            source="godropship",
            title="Wireless Earbuds Bluetooth 5.0 TWS",
            price=3.80,
            url="https://godropship.com/product/456",
            delivery_days_min=7,
            delivery_days_max=18,
            verified=True,
        ),
    ],
    "joybuy": [
        ScrapedProduct(
            source="joybuy",
            title="Bluetooth 5.0 TWS Wireless Earbuds",
            price=4.10,
            url="https://joybuy.com/product/789",
            delivery_days_min=7,
            delivery_days_max=21,
            verified=True,
        ),
    ],
    "bandq": [],
    "toolstation": [],
}


def get_mock_ebay_search(query: str, limit: int = 5) -> list[ScrapedProduct]:
    """Return mock eBay search results."""
    return MOCK_EBAY_PRODUCTS[:limit]


def get_mock_demand(query: str) -> DemandData:
    """Return mock demand data."""
    return MOCK_DEMAND


def get_mock_suppliers(query: str) -> dict[str, list[ScrapedProduct]]:
    """Return mock supplier results."""
    return MOCK_SUPPLIERS
