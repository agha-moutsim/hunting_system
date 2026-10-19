"""THE fee implementation - one model, one place, versioned.

Why this module exists (docs/plans/2026-10-19-feature-expansion, Phase D):
a fee figure computed in the pipeline and again in the UI will disagree, so
every fee in this product comes from here. `engine/profit.py` (the C3 money
rule) and the /fees calculator both call into this file; nothing else does
the arithmetic.

Two tables are shipped:

  uk-rate-card-2026-09-30   the published eBay UK structure - the active
                            table. Business seller: variable final value
                            fee by category (some tiered), per-order fee,
                            0.35% regulatory operating fee, all quoted
                            exclusive of VAT. UK-resident private seller:
                            no final value fee and no regulatory fee,
                            fees quoted VAT-inclusive.
  v1-static                 the flat 13.5% + 0.03% listing + 20% VAT model
                            of CONSTRAINTS.md C3, kept selectable so old
                            verdicts can be reproduced and compared. It
                            predates this module and is known to omit the
                            per-order, regulatory and category structure -
                            see docs/p0-research.md Q3 for the measured
                            deltas.

Where the numbers come from - no fee in this file was guessed. eBay's live
fee pages are bot-walled (a direct fetch on 2026-10-19 returned eBay's
"Please verify yourself" challenge, which is never parsed), so the table is
transcribed from Wayback Machine captures of the published pages:

  business   ebay.co.uk/help/selling/fees-credits-invoices/fees-business-sellers?id=4809
             page states "Last updated on 30 September, 2026"
             capture 20261005144021 (2026-10-05 14:40 UTC)
  private    ebay.co.uk/help/selling/fees-credits-invoices/fees-private-sellers?id=4822
             page states "Last updated on 1 October, 2024"
             capture 20260906221844 (2026-09-06 22:18 UTC)

Rules this module must keep obeying:

  - A response always states the table version it used (stale is visible,
    not silent).
  - An unread price is not a zero price: price=None must not produce a
    calculation (enforced in calculate_fees, see below).
  - Do not guess a fee. A category the table does not carry resolves to an
    explicit, stated default and is flagged `known=False`, never silently
    priced as if the category had been read.
  - A fee the table does not carry is absent from the result, not zero.

Deliberately NOT modelled, and said so rather than estimated:

  - Motors (Cars, Motorcycles & Vehicles) fees - a separate schedule on a
    separate page, and not this product's niche.
  - eBay Live fees and Classified Ad listing fees - separate schedules.
  - Optional listing upgrade fees (subtitle, gallery plus, reserve...) -
    per-listing choices, not part of a sale's fee structure.
  - Seller performance modifiers (Below Standard +6pp, very high INR +4pp)
    and the Top-rated Premium Service discount - documented on the rate
    card and carried in the table data, but only applied when the caller
    states them; the defaults assume a seller not affected by either.
  - VAT on the seller's own sale price (output VAT) - the calculator
    answers what eBay takes; it is not a VAT return.
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATE_CARD_TABLE = "uk-rate-card-2026-09-30"
V1_STATIC_TABLE = "v1-static"

# The table the pipeline verdict and the calculator use unless a caller asks
# otherwise. Named here once so a later switch is one line, not a hunt.
ACTIVE_TABLE = RATE_CARD_TABLE

# Everything Else (#99) - eBay's own catch-all category on the rate card, so
# an unknown category resolves to a real published row rather than an invented
# average. The resolution is still flagged: using it is a stated default, not
# a reading.
DEFAULT_CATEGORY_KEY = "everything-else"

_SOURCES = {
    "business": {
        "label": "eBay UK - Fees for business sellers (id=4809)",
        "url": "https://www.ebay.co.uk/help/selling/fees-credits-invoices/fees-business-sellers?id=4809",
        "page_updated": "2026-09-30",
        "retrieved": "Wayback capture 20261005144021",
    },
    "private": {
        "label": "eBay UK - Fees for private sellers (id=4822)",
        "url": "https://www.ebay.co.uk/help/selling/fees-credits-invoices/fees-private-sellers?id=4822",
        "page_updated": "2024-10-01",
        "retrieved": "Wayback capture 20260906221844",
    },
}

# ---------------------------------------------------------------------------
# The published UK rate card, as data
# ---------------------------------------------------------------------------
#
# Category rows: `tiers` is a list of (upper_limit, percent) pairs; each
# percent applies to the portion of the total amount of the sale (item price
# + postage + any applicable taxes) up to its limit, and the final (None, x)
# applies to everything above the previous limit. A single (None, x) is a
# flat rate.
#
# `rate_switch` (Trainers only): the card states a different flat rate when
# the item selling price (excluding postage) reaches a threshold. The
# threshold test uses the item price; the switched rate is applied to the
# total amount of the sale, like every other category rate.

_UK_BUSINESS_CATEGORIES = [
    {"key": "antiques", "name": "Antiques", "category_ids": [20081], "tiers": [(None, 10.9)]},
    {"key": "art", "name": "Art", "category_ids": [550], "tiers": [(None, 10.9)],
     "notes": ["Art NFTs are a separate row on the rate card (5%)."]},
    {"key": "art-nfts", "name": "Art - NFTs", "category_ids": [262051], "tiers": [(None, 5.0)]},
    {"key": "baby", "name": "Baby", "category_ids": [2984], "tiers": [(None, 10.9)]},
    {"key": "books-comics-magazines", "name": "Books, Comics & Magazines", "category_ids": [267], "tiers": [(None, 9.9)]},
    {"key": "business-office-industrial", "name": "Business, Office & Industrial", "category_ids": [12576], "tiers": [(None, 12.5)]},
    {"key": "cameras-photography", "name": "Cameras & Photography", "category_ids": [625], "tiers": [(None, 9.9)],
     "notes": ["Camcorders, Digital Cameras, Film Photography and Lenses & Filters have their own row (6.9% up to GBP 1,000, then 3%)."]},
    {"key": "cameras-photography-core", "name": "Cameras & Photography - Camcorders, Digital Cameras, Film Photography, Lenses & Filters", "category_ids": [11724, 31388, 69323, 78997], "tiers": [(1000.0, 6.9), (None, 3.0)]},
    {"key": "clothes-shoes-accessories", "name": "Clothes, Shoes & Accessories", "category_ids": [11450], "tiers": [(None, 11.9)],
     "notes": ["Women's Bags & Handbags and Trainers have their own rows."]},
    {"key": "clothes-womens-bags-handbags", "name": "Clothes, Shoes & Accessories - Women's Bags & Handbags", "category_ids": [169291], "tiers": [(800.0, 12.9), (None, 7.0)]},
    {"key": "clothes-trainers", "name": "Clothes, Shoes & Accessories - Trainers (men's and women's)", "category_ids": [15709, 95672], "tiers": [(None, 11.9)],
     "rate_switch": {"item_price_at_least": 100.0, "percent": 7.0},
     "notes": ["7% when the item selling price (excluding postage) is GBP 100 or more."]},
    {"key": "coins", "name": "Coins", "category_ids": [11116], "tiers": [(450.0, 10.9), (None, 3.0)]},
    {"key": "collectables", "name": "Collectables", "category_ids": [1], "tiers": [(None, 10.9)],
     "notes": ["Emerging NFTs and Non-Sport Trading Card NFTs have their own row (5%).",
               "Selected Collectables listings with orders up to GBP 10 have a reduced 10p per-order fee; the rate card links the exact subcategory list."]},
    {"key": "collectables-nfts", "name": "Collectables - Emerging NFTs, Non-Sport Trading Card NFTs", "category_ids": [262050, 262052], "tiers": [(None, 5.0)]},
    {"key": "computers-tablets-networking", "name": "Computers, Tablets & Networking", "category_ids": [58058], "tiers": [(None, 9.9)],
     "notes": ["Desktops & All-In-Ones, Drives/Storage, Enterprise Networking/Servers, Tablets & eBook Readers, Laptops & Netbooks and Printers/Scanners & Supplies have their own row (6.9% up to GBP 1,000, then 3%)."]},
    {"key": "computers-tablets-networking-core", "name": "Computers, Tablets & Networking - Desktops, Drives & Storage, Enterprise Networking, Tablets & eBook Readers, Laptops & Netbooks, Printers & Scanners", "category_ids": [171957, 165, 175698, 171485, 175672, 171961], "tiers": [(1000.0, 6.9), (None, 3.0)]},
    {"key": "crafts", "name": "Crafts", "category_ids": [14339], "tiers": [(None, 12.9)]},
    {"key": "dolls-bears", "name": "Dolls & Bears", "category_ids": [237], "tiers": [(None, 10.9)]},
    {"key": "event-tickets", "name": "Event Tickets", "category_ids": [1305], "tiers": [(None, 12.9)]},
    {"key": "films-tv", "name": "Films & TV", "category_ids": [11232], "tiers": [(None, 9.9)],
     "notes": ["Film NFTs are a separate row on the rate card (5%)."]},
    {"key": "films-tv-nfts", "name": "Films & TV - NFTs", "category_ids": [262053], "tiers": [(None, 5.0)]},
    {"key": "garden-patio", "name": "Garden & Patio", "category_ids": [159912], "tiers": [(None, 10.9)]},
    {"key": "health-beauty", "name": "Health & Beauty", "category_ids": [26395], "tiers": [(None, 10.9)],
     "notes": ["Hair Extensions & Wigs and Electronic Smoking, Parts & Accessories have their own rows."]},
    {"key": "health-beauty-hair-wigs", "name": "Health & Beauty - Hair Extensions & Wigs", "category_ids": [182101], "tiers": [(None, 11.9)]},
    {"key": "health-beauty-smoking", "name": "Health & Beauty - Electronic Smoking, Parts & Accessories", "category_ids": [183497], "tiers": [(None, 12.9)]},
    {"key": "holidays-travel", "name": "Holidays & Travel", "category_ids": [3252], "tiers": [(650.0, 7.9), (None, 3.0)]},
    {"key": "home-furniture-diy", "name": "Home, Furniture & DIY", "category_ids": [11700], "tiers": [(500.0, 11.9), (None, 7.9)],
     "notes": ["Appliances/DIY Tools, Power Strips and Furniture/Bath/Plumbing have their own rows.",
               "Selected Home, Furniture & DIY listings with orders up to GBP 10 have a reduced 10p per-order fee; the rate card links the exact subcategory list."]},
    {"key": "home-furniture-diy-appliances", "name": "Home, Furniture & DIY - Appliances, DIY Tools & Workshop Equipment", "category_ids": [20710, 631], "tiers": [(400.0, 6.9), (None, 3.0)]},
    {"key": "home-furniture-diy-power-strips", "name": "Home, Furniture & DIY - Power Strips & Surge Protectors", "category_ids": [67779], "tiers": [(250.0, 9.9), (None, 7.9)]},
    {"key": "home-furniture-diy-furniture", "name": "Home, Furniture & DIY - Furniture, Bath, Other Home Plumbing & Fixtures", "category_ids": [3197, 26677, 3191], "tiers": [(500.0, 10.9), (1000.0, 7.9), (None, 3.0)]},
    {"key": "jewellery-watches", "name": "Jewellery & Watches", "category_ids": [281], "tiers": [(1000.0, 14.9), (None, 4.0)],
     "notes": ["Watches, Parts & Accessories have their own row."]},
    {"key": "jewellery-watches-watches", "name": "Jewellery & Watches - Watches, Parts & Accessories", "category_ids": [260324], "tiers": [(750.0, 12.9), (None, 3.0)]},
    {"key": "mobile-phones-communication", "name": "Mobile Phones & Communication", "category_ids": [15032], "tiers": [(None, 9.9)],
     "notes": ["Mobile & Smart Phones have their own row."]},
    {"key": "mobile-phones-smartphones", "name": "Mobile Phones & Communication - Mobile & Smart Phones", "category_ids": [9355], "tiers": [(1000.0, 6.9), (None, 3.0)]},
    {"key": "music", "name": "Music", "category_ids": [11233], "tiers": [(None, 9.9)],
     "notes": ["Music NFTs are a separate row on the rate card (5%)."]},
    {"key": "music-nfts", "name": "Music - NFTs", "category_ids": [262054], "tiers": [(None, 5.0)]},
    {"key": "musical-instruments-dj", "name": "Musical Instruments & DJ Equipment", "category_ids": [619], "tiers": [(None, 10.9)]},
    {"key": "pet-supplies", "name": "Pet Supplies", "category_ids": [1281], "tiers": [(None, 12.9)]},
    {"key": "pottery-ceramics-glass", "name": "Pottery, Ceramics & Glass", "category_ids": [870], "tiers": [(None, 10.9)]},
    {"key": "sound-vision", "name": "Sound & Vision", "category_ids": [293], "tiers": [(None, 9.9)],
     "notes": ["DVD/Blu-ray & Home Cinema, Headphones, Home Audio & HiFi Separates and Televisions have their own row (6.9% up to GBP 1,000, then 3%)."]},
    {"key": "sound-vision-core", "name": "Sound & Vision - DVD/Blu-ray & Home Cinema, Headphones, Home Audio & HiFi, Televisions", "category_ids": [32852, 112529, 14969, 11071], "tiers": [(1000.0, 6.9), (None, 3.0)]},
    {"key": "sporting-goods", "name": "Sporting Goods", "category_ids": [888], "tiers": [(None, 10.9)]},
    {"key": "sports-memorabilia", "name": "Sports Memorabilia", "category_ids": [64482], "tiers": [(None, 10.9)],
     "notes": ["Sport Trading Card NFTs have their own row (5%)."]},
    {"key": "sports-memorabilia-nfts", "name": "Sports Memorabilia - Sport Trading Card NFTs", "category_ids": [262055], "tiers": [(None, 5.0)]},
    {"key": "stamps", "name": "Stamps", "category_ids": [260], "tiers": [(None, 10.9)]},
    {"key": "toys-games", "name": "Toys & Games", "category_ids": [220], "tiers": [(None, 10.9)],
     "notes": ["CCG NFTs and Tents have their own rows."]},
    {"key": "toys-games-nfts", "name": "Toys & Games - CCG NFTs", "category_ids": [262056], "tiers": [(None, 5.0)]},
    {"key": "toys-games-tents", "name": "Toys & Games - Tents", "category_ids": [117213], "tiers": [(250.0, 10.9), (None, 7.9)]},
    {"key": "vehicle-parts-accessories", "name": "Vehicle Parts & Accessories", "category_ids": [131090], "tiers": [(750.0, 9.5), (None, 3.0)],
     "notes": ["Tyres, GPS & Sat Nav Devices and Power Tools & Equipment have their own row (6.9% up to GBP 750, then 3%)."]},
    {"key": "vehicle-parts-accessories-core", "name": "Vehicle Parts & Accessories - Tyres, GPS & Sat Nav, Power Tools & Equipment", "category_ids": [179680, 124313, 139835, 35000], "tiers": [(750.0, 6.9), (None, 3.0)]},
    {"key": "video-games-consoles", "name": "Video Games & Consoles", "category_ids": [1249], "tiers": [(None, 9.9)],
     "notes": ["Video Game Consoles have their own row."]},
    {"key": "video-games-consoles-hardware", "name": "Video Games & Consoles - Video Game Consoles", "category_ids": [139971], "tiers": [(400.0, 6.9), (None, 2.0)]},
    {"key": "wholesale-job-lots", "name": "Wholesale & Job Lots", "category_ids": [40005], "tiers": [(None, 12.9)]},
    {"key": "everything-else", "name": "Everything Else", "category_ids": [99], "tiers": [(None, 12.9)],
     "notes": ["Memorials & Funerals have their own row (11.9%)."]},
    {"key": "memorials-funerals", "name": "Everything Else - Memorials & Funerals", "category_ids": [88739], "tiers": [(None, 11.9)]},
]

_UK_RATE_CARD = {
    "key": RATE_CARD_TABLE,
    "version": "eBay UK rate card - business page updated 2026-09-30, private page updated 2024-10-01",
    "currency": "GBP",
    "vat_rate": 20.0,
    "sources": [_SOURCES["business"], _SOURCES["private"]],
    "business": {
        "fees_include_vat": False,
        "categories": _UK_BUSINESS_CATEGORIES,
        "per_order_fee": {
            "at_or_below": 10.0,
            "fee_at_or_below": 0.30,
            "fee_above": 0.40,
        },
        "regulatory_fee_percent": 0.35,
        "listing_fee_guidance": {
            "no_shop": 0.30,
            "note": "30p per additional fixed-price listing without a Shop; Basic 250, Featured 1,500, Anchor unlimited free fixed-price listings per month. Private equivalent: 300 free listings per month, then 35p.",
        },
        "modifiers": {
            "below_standard_extra_pp": 6.0,
            "below_standard_extra_pp_after_4_months": 7.0,
            "very_high_inr_extra_pp": 4.0,
            "very_high_inr_extra_pp_after_4_months": 5.0,
            "top_rated_premium_service_discount_percent": 10.0,
            "note": "The Top-rated discount applies to the variable portion of the final value fee, not the per-order fee.",
        },
        "international_fee_percent": {
            "uk": 0.0,
            "eu_northern_europe": 1.05,
            "us_canada": 1.8,
            "rest_of_world": 2.0,
        },
    },
    "private": {
        # UK-resident private sellers (the paragraph the page leads with).
        "uk_resident": True,
        "fees_include_vat": True,
        "fvf_percent": 0.0,
        "regulatory_fee_percent": 0.0,
        "free_listings_per_month": 300,
        "listing_fee_after_allowance": 0.35,
        "international_fee_percent": 3.0,
        "excludes": "Cars, Motorcycles & Vehicles (Motors) - a separate schedule",
        "notes": [
            "The private page states it is free for UK-based private sellers to sell: no final value fees and no regulatory operating fees when items sell.",
            "Fees on this page are inclusive of VAT at 20%.",
        ],
        "non_uk_resident": {
            # Documented on the same page, under "Fees for private sellers
            # residing outside the UK".
            "fvf_tiers": [(5000.0, 12.8), (None, 3.0)],
            "per_order_fee": 0.30,
            "regulatory_fee_percent": 0.42,
            "notes": [
                "12.8% of the total amount of the sale plus a fixed 30p per order; 3% applies to the portion above GBP 5,000 for a single item.",
                "Trainers: 8% + 30p when the selling price (per item) is GBP 100 or more.",
                "The regulatory operating fee is stated as 0.42% on this section (VAT-inclusive).",
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# v1-static - the C3 model, kept for reproduction and comparison
# ---------------------------------------------------------------------------

_V1_STATIC = {
    "key": V1_STATIC_TABLE,
    "version": "v1-static (CONSTRAINTS.md C3)",
    "currency": "GBP",
    "vat_rate": 20.0,
    "sources": [
        {
            "label": "CONSTRAINTS.md C3 - the flat model: 13.5% final value fee + 0.03% listing fee + 20% VAT on eBay's fees + 3% returns buffer",
            "url": None,
            "page_updated": None,
            "retrieved": None,
        }
    ],
    "notes": [
        "Superseded by the published rate card. Kept selectable so verdicts produced before the switch can be reproduced and compared.",
        "Known deltas (docs/p0-research.md Q3): no category rates, no per-order fee, no regulatory operating fee, listing cost modelled as 0.03% of the sale instead of a per-listing charge.",
    ],
    "business": {
        "fees_include_vat": False,
        "categories": None,  # no category model - everything gets the flat rate
        "fvf_percent": 13.5,
        "listing_fee_percent": 0.03,
        "per_order_fee": None,
        "regulatory_fee_percent": None,
        "international_fee_percent": None,
    },
    "private": {
        "uk_resident": True,
        "fees_include_vat": False,
        "fvf_percent": 13.5,
        "listing_fee_percent": 0.03,
        "regulatory_fee_percent": None,
        "per_order_fee": None,
        "international_fee_percent": None,
    },
}

FEE_TABLES: dict[str, dict] = {
    RATE_CARD_TABLE: _UK_RATE_CARD,
    V1_STATIC_TABLE: _V1_STATIC,
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get_fee_table(key: Optional[str] = None) -> dict:
    """Return a fee table by key; None or "" means the active table.

    An unknown key raises rather than silently falling back - a caller that
    asked for a table we do not have must hear about it.
    """
    name = key or ACTIVE_TABLE
    if name not in FEE_TABLES:
        raise KeyError(
            f"unknown fee table {name!r}; known tables: {sorted(FEE_TABLES)}"
        )
    return FEE_TABLES[name]


def seller_side(table: dict, seller_type: str, uk_resident: bool = True) -> dict:
    """The table's section for a seller type.

    Business is business. Private splits into UK-resident (no final value
    fee, no regulatory fee) and non-UK-resident (its own documented
    schedule) - the two are different fee structures and must not share one.
    """
    if seller_type == "business":
        return table["business"]
    if seller_type == "private":
        if not uk_resident:
            side = dict(table["private"])
            side.update(side.pop("non_uk_resident"))
            side["fvf_percent"] = None  # the non-UK schedule is tiered
            return side
        return table["private"]
    raise ValueError(f"unknown seller_type {seller_type!r}; expected 'business' or 'private'")


def resolve_category(
    category, table: Optional[dict] = None
) -> tuple[Optional[dict], bool]:
    """Resolve a category key or category id to a rate-card row.

    Returns (row, known). `None`, an empty value, or anything the table does
    not carry resolves to the stated default row (Everything Else) with
    known=False - the caller must say the category was not identified rather
    than price it as if it were read.
    """
    tbl = table or get_fee_table()
    categories = (tbl.get("business") or {}).get("categories")
    if not categories:
        # v1-static has no category model - every sale is the flat rate.
        return None, False

    if category is None or category == "":
        return _default_row(categories), False

    needle = str(category).strip().lower()
    for row in categories:
        if row["key"] == needle:
            return row, True
    # A category id (int or numeric string) resolves against category_ids.
    try:
        number = int(needle)
    except (TypeError, ValueError):
        return _default_row(categories), False
    for row in categories:
        if number in row["category_ids"]:
            return row, True
    return _default_row(categories), False


def _default_row(categories: list[dict]) -> dict:
    for row in categories:
        if row["key"] == DEFAULT_CATEGORY_KEY:
            return row
    raise KeyError(f"rate card has no {DEFAULT_CATEGORY_KEY!r} row to default to")


def rate_label(row: dict, currency: str = "GBP") -> str:
    """A human-readable statement of a category row's rate(s).

    Kept next to the data so the UI and the tests describe the rate the
    same way - and so a tiered rate can never render as if it were flat.
    """
    parts: list[str] = []
    lower = 0.0
    for upper, percent in row["tiers"]:
        pct = f"{percent:g}%"
        if upper is None:
            parts.append(pct if not parts else f"{pct} above {currency} {lower:,.0f}")
        else:
            parts.append(f"{pct} up to {currency} {upper:,.0f}")
            lower = upper
    label = ", then ".join(parts)
    switch = row.get("rate_switch")
    if switch:
        label += (
            f" ({switch['percent']:g}% when the item price is "
            f"{currency} {switch['item_price_at_least']:,.0f} or more, excluding postage)"
        )
    return label


def list_categories(table: Optional[dict] = None) -> list[dict]:
    """UI-ready category rows for a table: key, name, ids, rate label."""
    tbl = table or get_fee_table()
    categories = (tbl.get("business") or {}).get("categories") or []
    return [
        {
            "key": row["key"],
            "name": row["name"],
            "category_ids": row["category_ids"],
            "rate_label": rate_label(row, tbl.get("currency", "GBP")),
            "notes": row.get("notes", []),
        }
        for row in categories
    ]
