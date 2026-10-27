"""THE fee implementation - one model, one place, versioned.

Why this module exists (docs/plans/2026-10-19-feature-expansion, Phase D):
a fee figure computed in the pipeline and again in the UI will disagree, so
every fee in this product comes from here. `engine/profit.py` (the C3 money
rule) and the /fees calculator both call into this file; nothing else does
the arithmetic.

Three tables are shipped:

  uk-rate-card-2026-09-30   the published eBay UK structure - the active
                            table. Business seller: variable final value
                            fee by category (some tiered), per-order fee,
                            0.35% regulatory operating fee, all quoted
                            exclusive of VAT. UK-resident private seller:
                            no final value fee and no regulatory fee,
                            fees quoted VAT-inclusive.
  au-rate-card-2026-10-09   the published eBay Australia structure. Two
                            branches: eBay Pro (four plans, category tiers,
                            per-order fee, 1.1% international fee) and
                            free-selling (no final value fee, 3%
                            international fee, label mandate). Fees are
                            quoted GST-inclusive. Registered here in Phase
                            B; the per-market config selects it in Phase C.
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

import math
from typing import Optional

from config import PROFIT_CONFIG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATE_CARD_TABLE = "uk-rate-card-2026-09-30"
AU_RATE_CARD_TABLE = "au-rate-card-2026-10-09"
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
        "fee_basis": "total_amount_of_sale",
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
        "fee_basis": "total_amount_of_sale",
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
# The published AU rate card, as data
# ---------------------------------------------------------------------------
#
# Source: docs/au-market/fee-research.md (Phase A). Every number below is
# transcribed from an eBay.com.au page; no third-party calculator is a
# source. The card is registered here but is not the active table - Phase C
# selects it per marketplace. Keeping the data in one module means the
# pipeline and the calculator can never price an AU sale from different
# numbers.

_AU_SOURCES = {
    "business": {
        "label": "eBay Australia - eBay Pro selling fees (id=4809)",
        "url": "https://www.ebay.com.au/help/selling/fees-credits-invoices/ebay-pro-selling-fees?id=4809",
        "page_updated": "2026-10-09",
        "retrieved": "Wayback capture 20261017110035",
    },
    "private": {
        "label": "eBay Australia - Selling fees without a Pro plan (id=4822)",
        "url": "https://www.ebay.com.au/help/selling/fees-credits-invoices/selling-fees-without-pro-plan?id=4822",
        "page_updated": "2026-10-09",
        "retrieved": "Wayback capture 20261012003957",
    },
    "label": {
        "label": "eBay Australia - Buying shipping labels on eBay (id=4157)",
        "url": "https://www.ebay.com.au/help/selling/shipping-items/labels-packaging-tips/buying-shipping-labels?id=4157",
        "page_updated": None,
        "date_note": (
            "No date line on the article; the capture is used for the label "
            "mandate and its four exceptions."
        ),
        "retrieved": "Wayback capture 20260908071955",
    },
}

_AU_RATE_CARD = {
    "key": AU_RATE_CARD_TABLE,
    "version": (
        "eBay AU rate card - Pro and free-selling pages updated 2026-10-09"
    ),
    "currency": "AUD",
    "tax_name": "GST",
    "gst_rate": 10.0,
    "domestic_region": "au",
    # The free-selling (Individual) branch is the default for an AU seller;
    # a business seller selects a Pro plan at runtime.
    "default_seller_type": "private",
    # Tier 2 is the published "all other items" row, so an unresolved
    # category defaults to a real row with known=False - never an invented
    # average.
    "default_category_key": "tier-2",
    # These parent IDs appear as headings in both the Tier 1 and Tier 4
    # lists. The page does not state a precedence rule, so a listing in one
    # of these parents resolves to the stated Tier 2 default with
    # known=False rather than being assigned to one tier by table order.
    "ambiguous_category_ids": [625, 293, 172176, 15032, 1249],
    "sources": [
        _AU_SOURCES["business"],
        _AU_SOURCES["private"],
        _AU_SOURCES["label"],
    ],
    "notes": [
        "All fees are in Australian dollars unless otherwise stated.",
        "GST at 10% is included in the displayed fees unless the seller has "
        "registered tax-exempt status with an ABN; this card stores the "
        "displayed inclusive numbers and does not add a GST-on-fees line.",
        "The Pro Starter rate is 13.4% in all four tiers: the captured cell "
        "carries rowspan=4.",
        "Parent category IDs repeated across Tier 1 and Tier 4 are ambiguous "
        "and resolve to the stated Tier 2 default with known=False.",
        "Currency conversion is 3.0% through 31 October 2026 and 3.25% from "
        "1 November 2026; it does not apply to a domestic AUD sale.",
        "Rounding is standard two-decimal AUD rounding; eBay does not state a "
        "rounding rule on these pages.",
        "The label price is postage, not an eBay fee, and is not priced by "
        "this card.",
    ],
    # Filled in by the next commits: the two seller branches are kept
    # separate because they price different populations and must never share
    # a rate by accident.
    "business": {},
    "private": {},
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
        "fee_basis": "item_price",
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
        "fee_basis": "item_price",
        "fvf_percent": 13.5,
        "listing_fee_percent": 0.03,
        "regulatory_fee_percent": None,
        "per_order_fee": None,
        "international_fee_percent": None,
    },
}

FEE_TABLES: dict[str, dict] = {
    RATE_CARD_TABLE: _UK_RATE_CARD,
    AU_RATE_CARD_TABLE: _AU_RATE_CARD,
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


def tiers_label(tiers: list, currency: str = "GBP") -> str:
    """A human-readable statement of a tier list, so a tiered rate can never
    render as if it were flat."""
    parts: list[str] = []
    lower = 0.0
    for upper, percent in tiers:
        pct = f"{percent:g}%"
        if upper is None:
            parts.append(pct if not parts else f"{pct} above {currency} {lower:,.0f}")
        else:
            parts.append(f"{pct} up to {currency} {upper:,.0f}")
            lower = upper
    return ", then ".join(parts)


def rate_label(row: dict, currency: str = "GBP") -> str:
    """A category row's rate(s), including its rate switch when it has one."""
    label = tiers_label(row["tiers"], currency)
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


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------

BUYER_REGIONS = {
    "uk": "UK",
    "eu_northern_europe": "Eurozone & Northern Europe",
    "us_canada": "US & Canada",
    "rest_of_world": "all other countries",
}


def _as_amount(value, field: str, *, minimum: float = 0.0) -> float:
    """A money amount from a caller. Refuses None - an unread value is not a
    zero - and refuses NaN, which would poison every downstream sum."""
    if value is None:
        raise ValueError(f"{field} is required")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, got {value!r}")
    if number != number:  # NaN
        raise ValueError(f"{field} must be a number, got NaN")
    if number < minimum:
        raise ValueError(f"{field} must be at least {minimum:g}, got {number:g}")
    return number


def _tier_fee(tiers: list, amount: float) -> float:
    """Fee from (upper_limit, percent) pairs applied to an amount. Raw."""
    fee = 0.0
    lower = 0.0
    for upper, percent in tiers:
        if upper is None:
            fee += max(0.0, amount - lower) * percent / 100.0
            break
        fee += max(0.0, min(amount, upper) - lower) * percent / 100.0
        lower = upper
    return fee


def calculate_fees(
    sale_price,
    *,
    postage_charged: float = 0.0,
    category=None,
    promoted_rate: float = 0.0,
    seller_type: str = "business",
    uk_resident: bool = True,
    vat_registered: bool = False,
    listing_fee: float = 0.0,
    buyer_region: str = "uk",
    fee_table: Optional[str] = None,
) -> dict:
    """The eBay fees on one sale. Every fee figure in the product comes from
    here (one implementation per calculation - constraints.md section 5).

    Raises ValueError, never prints a guess:

      - sale_price None/<= 0        there is no such sale to price
      - promoted_rate < 0 or >= 100 not a rate, an input error
      - unknown seller_type         business or private only
      - unknown buyer_region        one of BUYER_REGIONS

    A fee the table does not carry is absent (None), not zero. A fee the
    table carries as zero - a UK private seller's final value fee - is a
    stated zero and stays a number. The two must not look alike (C1).
    """
    if sale_price is None:
        raise ValueError(
            "sale_price is required - an unread price is not a zero price"
        )
    price = _as_amount(sale_price, "sale_price")
    if price <= 0:
        raise ValueError(
            "sale_price must be greater than zero; a zero-priced sale is not "
            "a sale, and zero fees on it would read as a measurement"
        )
    postage = _as_amount(postage_charged, "postage_charged")
    listing = _as_amount(listing_fee, "listing_fee")
    promoted = _as_amount(promoted_rate, "promoted_rate")
    if promoted >= 100:
        raise ValueError(
            f"promoted_rate must be below 100 (a percentage of the sale), got {promoted:g}"
        )
    if buyer_region not in BUYER_REGIONS:
        raise ValueError(
            f"unknown buyer_region {buyer_region!r}; expected one of {sorted(BUYER_REGIONS)}"
        )

    tbl = get_fee_table(fee_table)
    side = seller_side(tbl, seller_type, uk_resident=uk_resident)
    currency = tbl["currency"]
    basis = side.get("fee_basis", "total_amount_of_sale")
    total = price + postage if basis == "total_amount_of_sale" else price

    assumptions: list[str] = []
    notes: list[str] = []

    # --- Final value fee ---
    category_info: Optional[dict] = None
    if side.get("categories"):
        row, known = resolve_category(category, tbl)
        label = rate_label(row, currency)
        switch = row.get("rate_switch")
        if switch and price >= switch["item_price_at_least"]:
            fvf = total * switch["percent"] / 100.0
            applied = (
                f"{switch['percent']:g}% (item price {currency} "
                f"{switch['item_price_at_least']:,.0f} or more, excluding postage)"
            )
        else:
            fvf = _tier_fee(row["tiers"], total)
            applied = label
        category_info = {
            "key": row["key"],
            "name": row["name"],
            "category_ids": row["category_ids"],
            "known": known,
            "rate_label": label,
            "rate_applied": applied,
        }
        notes.extend(row.get("notes", []))
        if not known:
            assumptions.append(
                f"No category identified; using {row['name']} ({label}) - a "
                "stated default, not a reading of your category."
            )
    elif side.get("fvf_tiers"):
        fvf = _tier_fee(side["fvf_tiers"], total)
        applied = tiers_label(side["fvf_tiers"], currency)
    else:
        fvf = total * side["fvf_percent"] / 100.0
        applied = f"{side['fvf_percent']:g}%"

    # --- Per-order fee: a published step, so the boundary is inclusive ---
    pof = side.get("per_order_fee")
    if isinstance(pof, dict):
        per_order: Optional[float] = (
            pof["fee_at_or_below"] if total <= pof["at_or_below"] else pof["fee_above"]
        )
    elif pof is not None:
        per_order = float(pof)
    else:
        per_order = None

    # --- Regulatory operating fee ---
    reg_percent = side.get("regulatory_fee_percent")
    regulatory = total * reg_percent / 100.0 if reg_percent is not None else None

    # --- Promoted listings: a chosen ad rate, applied when stated ---
    promoted_fee = total * promoted / 100.0 if promoted > 0 else None

    # v1-static models a listing component as a percent of the sale; the
    # published card charges per listing instead (the `listing_fee` input).
    listing_percent = side.get("listing_fee_percent")
    listing_percent_fee = total * listing_percent / 100.0 if listing_percent else None

    # --- International fee: only for a non-UK delivery address ---
    intl = side.get("international_fee_percent")
    if isinstance(intl, dict):
        intl_rate: Optional[float] = intl.get(buyer_region)
    elif intl is not None:
        intl_rate = 0.0 if buyer_region == "uk" else float(intl)
    else:
        intl_rate = None
    international = (
        total * intl_rate / 100.0 if intl_rate is not None and intl_rate > 0 else None
    )
    if buyer_region != "uk" and intl_rate is None:
        notes.append(
            "The international fee for this seller type is not on the rate "
            "card section used here; check your local fee page."
        )

    fee_lines_raw = [
        value
        for value in (
            fvf,
            per_order,
            regulatory,
            promoted_fee,
            international,
            listing if listing > 0 else None,
            listing_percent_fee,
        )
        if value is not None
    ]
    quoted_raw = sum(fee_lines_raw)

    # --- VAT: the two rate cards quote VAT differently, and that difference
    # is itself published - do not normalise it away ---
    vat_raw: Optional[float]
    if side.get("fees_include_vat"):
        vat_raw = None
        vat_recoverable: Optional[bool] = False
        vat_note = (
            "Private seller fees are quoted inclusive of VAT at "
            f"{tbl['vat_rate']:g}% on the private rate card; no VAT is added."
        )
        cost_raw = quoted_raw
    else:
        vat_raw = quoted_raw * tbl["vat_rate"] / 100.0
        vat_recoverable = bool(vat_registered) if seller_type == "business" else False
        cost_raw = quoted_raw if vat_recoverable else quoted_raw + vat_raw
        if seller_type == "business":
            if vat_recoverable:
                vat_note = (
                    f"{tbl['vat_rate']:g}% VAT is added to eBay's fees and shown "
                    "as recoverable (seller is VAT registered), so it is excluded "
                    "from the cost total. VAT charged on your own sale price is "
                    "out of scope of this calculator."
                )
            else:
                vat_note = (
                    f"{tbl['vat_rate']:g}% VAT is added to eBay's fees and is part "
                    "of the cost total (seller is not VAT registered)."
                )
        else:
            vat_note = (
                f"{tbl['vat_rate']:g}% VAT is added to eBay's fees on this schedule."
            )

    # --- Assumptions: stated so a default can never hide inside a total ---
    if basis == "total_amount_of_sale":
        assumptions.append(
            "Fees are calculated on the total amount of the sale: item "
            f"{currency} {price:,.2f} + postage charged {currency} {postage:,.2f}."
        )
    else:
        assumptions.append(
            "Fees are calculated on the item price only - this table predates "
            "postage-inclusive fee bases; the published rate card charges on "
            "the total amount of the sale."
        )
    if buyer_region == "uk":
        assumptions.append(
            "A UK delivery address is assumed; eBay's international fee is not included."
        )
    else:
        assumptions.append(
            f"Buyer region: {BUYER_REGIONS[buyer_region]}; the international fee "
            "above applies to deliveries outside the UK."
        )
    if listing <= 0 and listing_percent_fee is None:
        guidance = (tbl.get("business") or {}).get("listing_fee_guidance")
        guidance_text = f" {guidance['note']}" if guidance else ""
        assumptions.append(
            "Per-listing fees are not included (0.00 assumed)." + guidance_text
        )

    return {
        "ok": True,
        "fee_table": {
            "key": tbl["key"],
            "version": tbl["version"],
            "currency": currency,
        },
        "seller": {
            "type": seller_type,
            "uk_resident": bool(uk_resident) if seller_type == "private" else None,
            "vat_registered": bool(vat_registered) if seller_type == "business" else None,
        },
        "buyer_region": buyer_region,
        "category": category_info,
        "fee_basis": basis,
        "total_amount_of_sale": round(price + postage, 2),
        "fvf": round(fvf, 2),
        "fvf_rate": applied,
        "per_order_fee": round(per_order, 2) if per_order is not None else None,
        "regulatory_fee": round(regulatory, 2) if regulatory is not None else None,
        "promoted_fee": round(promoted_fee, 2) if promoted_fee is not None else None,
        "international_fee": round(international, 2) if international is not None else None,
        "listing_fee": (
            round(listing, 2)
            if listing > 0
            else (round(listing_percent_fee, 2) if listing_percent_fee is not None else None)
        ),
        "vat_on_fees": round(vat_raw, 2) if vat_raw is not None else None,
        "vat_recoverable": vat_recoverable,
        "vat_note": vat_note,
        "fees_quoted_total": round(quoted_raw, 2),
        "fees_gross_total": (
            round(quoted_raw + vat_raw, 2) if vat_raw is not None else round(quoted_raw, 2)
        ),
        "fees_cost_total": round(cost_raw, 2),
        # Raw, unrounded cost - engine-internal callers (profit, solver) use
        # this so rounding happens once, at the edge. The underscore marks it
        # as not part of the response contract.
        "_fees_cost_raw": cost_raw,
        "_total_amount_raw": total,
        "assumptions": assumptions,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# The money layer - one sale, all the way to profit and margin
# ---------------------------------------------------------------------------


def _displayed_postage_paid(postage_paid) -> tuple[float, bool]:
    """The seller's postage cost, as displayed, keeping the v1 rule intact:

    `0.0` means UNKNOWN, not free. A blank, non-numeric or negative reading
    is unknown; and the figure is rounded once, where it is shown, so a
    profit computed from it never disagrees with its own printed parts.
    """
    try:
        paid = float(postage_paid if postage_paid is not None else 0.0)
    except (TypeError, ValueError):
        paid = 0.0
    if paid != paid:  # NaN
        paid = 0.0
    displayed = round(paid, 2) if round(paid, 2) > 0 else 0.0
    return displayed, displayed > 0


def _cost_inputs(
    postage_paid, risk_buffer_percent, packaging_cost
) -> tuple[float, bool, float, float]:
    """The seller-side cost inputs. Buffer and packaging default to the C3
    config values when a caller does not state them."""
    paid, paid_known = _displayed_postage_paid(postage_paid)
    buffer_percent = float(
        PROFIT_CONFIG["returns_buffer_percent"]
        if risk_buffer_percent is None
        else risk_buffer_percent
    )
    if not (0.0 <= buffer_percent < 100.0):
        raise ValueError(
            f"risk_buffer_percent must be in [0, 100), got {buffer_percent:g}"
        )
    packaging = float(
        PROFIT_CONFIG["packaging_cost"] if packaging_cost is None else packaging_cost
    )
    if packaging < 0:
        raise ValueError(f"packaging_cost must be >= 0, got {packaging:g}")
    return paid, paid_known, buffer_percent, packaging


def _fee_lines(fees_view: dict) -> list[dict]:
    """The engine's own itemised lines, in the order the card reads.

    CLI, scorecard, the API and the calculator all render these same rows,
    so two surfaces can never label the same charge differently. Only a fee
    the table actually carries gets a line - an absent fee has no row to be
    misread as a zero (C1). The returns buffer is deliberately NOT here: it
    is the seller's own policy, not a charge by eBay, and travels beside
    these lines as `risk_buffer` with its own label.
    """
    table = get_fee_table(fees_view["fee_table"]["key"])
    seller = table.get(fees_view.get("seller", {}).get("type", "business")) or {}
    category = fees_view.get("category") or {}
    lines: list[dict] = [
        {
            "label": "Final value fee",
            "rate": category.get("rate_applied") or fees_view.get("fvf_rate"),
            "amount": fees_view["fvf"],
        }
    ]
    if fees_view.get("per_order_fee") is not None:
        lines.append(
            {"label": "Per-order fee", "rate": None, "amount": fees_view["per_order_fee"]}
        )
    if fees_view.get("regulatory_fee") is not None:
        percent = seller.get("regulatory_fee_percent")
        lines.append(
            {
                "label": "Regulatory operating fee",
                "rate": f"{percent:g}%" if percent is not None else None,
                "amount": fees_view["regulatory_fee"],
            }
        )
    if fees_view.get("international_fee") is not None:
        lines.append(
            {
                "label": "International fee",
                "rate": None,
                "amount": fees_view["international_fee"],
            }
        )
    if fees_view.get("promoted_fee") is not None:
        lines.append(
            {
                "label": "Promoted listings",
                "rate": None,
                "amount": fees_view["promoted_fee"],
            }
        )
    if fees_view.get("listing_fee") is not None:
        percent = seller.get("listing_fee_percent")
        lines.append(
            {
                "label": "Listing fee",
                "rate": f"{percent:g}%" if percent is not None else None,
                "amount": fees_view["listing_fee"],
            }
        )
    if fees_view.get("vat_on_fees") is not None:
        lines.append(
            {
                "label": "VAT on fees",
                "rate": f"{table['vat_rate']:g}%",
                "amount": fees_view["vat_on_fees"],
            }
        )
    return lines


def _raw_profit_at(price: float, *, supplier, paid_displayed: float, buffer_percent: float, packaging: float, fee_kwargs: dict) -> dict:
    """Raw (unrounded) money for one sale at one price.

    The single place the profit formula lives: proceeds minus eBay's cost
    view, minus postage paid, minus supplier, minus the risk buffer, minus
    packaging. Rounding happens only at the edges, once.
    """
    fees = calculate_fees(price, **fee_kwargs)
    cost_raw = fees["_fees_cost_raw"]
    proceeds_raw = price + float(fee_kwargs.get("postage_charged") or 0.0)
    buffer_raw = price * buffer_percent / 100.0
    profit_raw = (
        proceeds_raw
        - cost_raw
        - paid_displayed
        - (supplier if supplier is not None else 0.0)
        - buffer_raw
        - packaging
    )
    return {
        "fees": fees,
        "cost_raw": cost_raw,
        "proceeds_raw": proceeds_raw,
        "buffer_raw": buffer_raw,
        "profit_raw": profit_raw,
    }


def sale_outcome(
    sale_price,
    supplier_cost=None,
    postage_paid=0.0,
    *,
    risk_buffer_percent=None,
    packaging_cost=None,
    postage_charged=0.0,
    category=None,
    promoted_rate=0.0,
    seller_type="business",
    uk_resident=True,
    vat_registered=False,
    listing_fee=0.0,
    buyer_region="uk",
    fee_table=None,
) -> dict:
    """The whole money view of one sale: fees, net after them, profit, margin.

    The result carries the fee table that made it (`fees.fee_table`), the
    itemised rows every display surface renders (`fee_lines`), and the
    seller's own buffer outside the fees (`risk_buffer`).

    A missing supplier cost does not become a zero: the fee figures still
    compute (they do not need it), but `profit` and `margin` come back None
    with `profit_is_complete` False and a stated reason. The risk buffer is
    the seller's own policy (config by default), never an eBay fee - and it
    is labelled as a buffer wherever it is shown.
    """
    supplier: Optional[float]
    if supplier_cost is None:
        supplier = None
    else:
        try:
            supplier = float(supplier_cost)
        except (TypeError, ValueError):
            raise ValueError(f"supplier_cost must be a number, got {supplier_cost!r}")
        if supplier != supplier:  # NaN
            raise ValueError("supplier_cost must be a number, got NaN")

    paid_displayed, paid_known, buffer_percent, packaging = _cost_inputs(
        postage_paid, risk_buffer_percent, packaging_cost
    )

    fee_kwargs = {
        "postage_charged": postage_charged,
        "category": category,
        "promoted_rate": promoted_rate,
        "seller_type": seller_type,
        "uk_resident": uk_resident,
        "vat_registered": vat_registered,
        "listing_fee": listing_fee,
        "buyer_region": buyer_region,
        "fee_table": fee_table,
    }

    raw = _raw_profit_at(
        sale_price,
        supplier=supplier,
        paid_displayed=paid_displayed,
        buffer_percent=buffer_percent,
        packaging=packaging,
        fee_kwargs=fee_kwargs,
    )
    price_value = float(sale_price)
    supplier_known = supplier is not None
    profit_raw = raw["profit_raw"] if supplier_known else None
    margin_raw = (
        raw["profit_raw"] / price_value * 100.0 if supplier_known else None
    )

    result = {
        "ok": True,
        "fees": {k: v for k, v in raw["fees"].items() if not k.startswith("_")},
        "fee_lines": _fee_lines(raw["fees"]),
        "price": round(price_value, 2),
        "postage_charged": round(float(fee_kwargs["postage_charged"] or 0.0), 2),
        "proceeds": round(raw["proceeds_raw"], 2),
        "supplier_cost": round(supplier, 2) if supplier_known else None,
        "postage_paid": paid_displayed,
        "postage_paid_known": paid_known,
        "risk_buffer_percent": buffer_percent,
        "risk_buffer": round(raw["buffer_raw"], 2),
        "packaging_cost": round(packaging, 2),
        "net_after_fees": round(raw["proceeds_raw"] - raw["cost_raw"], 2),
        "profit": round(profit_raw, 2) if supplier_known else None,
        "margin": round(margin_raw, 1) if supplier_known else None,
        "profit_is_complete": bool(supplier_known and paid_known),
        "profit_missing_reason": (
            None
            if supplier_known
            else "supplier cost was not given - no profit figure is shown "
            "rather than a zero"
        ),
        # Raw, unrounded internals for engine callers (profit.py keeps the
        # legacy totals exact). Underscored: not part of the response shape.
        "_profit_raw": profit_raw,
        "_net_raw": raw["proceeds_raw"] - raw["cost_raw"],
        "_cost_raw": raw["cost_raw"],
        "_proceeds_raw": raw["proceeds_raw"],
        "_buffer_raw": raw["buffer_raw"],
        "_packaging_raw": packaging,
        "_shipping_displayed": paid_displayed,
    }
    return result


def solve_for_margin(
    target_margin,
    *,
    supplier_cost,
    postage_paid=0.0,
    risk_buffer_percent=None,
    packaging_cost=None,
    postage_charged=0.0,
    category=None,
    promoted_rate=0.0,
    seller_type="business",
    uk_resident=True,
    vat_registered=False,
    listing_fee=0.0,
    buyer_region="uk",
    fee_table=None,
) -> dict:
    """Reverse mode: the sale price that nets a target margin.

    The fee structure is piecewise linear in the price - category tiers, the
    per-order step, the Trainers switch - so the solver splits the price axis
    at exactly those breakpoints and solves each segment analytically, then
    proves the answer by recomputing the margin at the returned price
    (`check`). The returned price is rounded UP to the penny, so the quoted
    price meets the target rather than missing it by a rounding hair.

    Returns `achievable: False` with a stated reason when no price reaches
    the target - it never returns a price that does not.
    """
    try:
        m = float(target_margin)
    except (TypeError, ValueError):
        raise ValueError(
            f"target_margin must be a number, got {target_margin!r}"
        )
    if not (0.0 <= m < 100.0):
        raise ValueError(f"target_margin must be in [0, 100), got {m:g}")
    if supplier_cost is None:
        raise ValueError(
            "supplier_cost is required to solve for a price - without it "
            "there is no profit to target"
        )
    supplier = float(supplier_cost)
    if supplier != supplier:  # NaN
        raise ValueError("supplier_cost must be a number, got NaN")

    paid_displayed, _paid_known, buffer_percent, packaging = _cost_inputs(
        postage_paid, risk_buffer_percent, packaging_cost
    )
    fee_kwargs = {
        "postage_charged": postage_charged,
        "category": category,
        "promoted_rate": promoted_rate,
        "seller_type": seller_type,
        "uk_resident": uk_resident,
        "vat_registered": vat_registered,
        "listing_fee": listing_fee,
        "buyer_region": buyer_region,
        "fee_table": fee_table,
    }

    def outcome_at(p: float) -> dict:
        return _raw_profit_at(
            p,
            supplier=supplier,
            paid_displayed=paid_displayed,
            buffer_percent=buffer_percent,
            packaging=packaging,
            fee_kwargs=fee_kwargs,
        )

    def g(p: float) -> float:
        """profit(p) minus the target profit - the function to zero."""
        return outcome_at(p)["profit_raw"] - m / 100.0 * p

    def margin_at(p: float) -> float:
        return outcome_at(p)["profit_raw"] / p * 100.0

    # --- Breakpoints: where the fee structure changes slope or steps ---
    tbl = get_fee_table(fee_table)
    side = seller_side(tbl, seller_type, uk_resident=uk_resident)
    shift = float(postage_charged or 0.0)
    breakpoints: set[float] = set()
    if side.get("categories"):
        row, _known = resolve_category(category, tbl)
        for upper, _pct in row["tiers"]:
            if upper is not None:
                breakpoints.add(upper - shift)
        switch = row.get("rate_switch")
        if switch:
            breakpoints.add(switch["item_price_at_least"])
    elif side.get("fvf_tiers"):
        for upper, _pct in side["fvf_tiers"]:
            if upper is not None:
                breakpoints.add(upper - shift)
    pof = side.get("per_order_fee")
    if isinstance(pof, dict):
        breakpoints.add(pof["at_or_below"] - shift)

    bounds = sorted(b for b in breakpoints if b > 0.02)
    segments: list[tuple[float, Optional[float]]] = []
    lower = 0.0
    for b in bounds:
        segments.append((lower, b))
        lower = b
    segments.append((lower, None))

    # --- Solve each segment analytically (profit is linear inside one) ---
    exact: Optional[float] = None
    for seg_lo, seg_hi in segments:
        if seg_hi is None:
            p1 = max(seg_lo, 0.0) + 0.05
            p2 = p1 + 1.0
        else:
            span = seg_hi - seg_lo
            p1 = seg_lo + span * 0.25
            p2 = seg_lo + span * 0.75
        if p2 <= p1:
            continue
        g1, g2 = g(p1), g(p2)
        slope = (g2 - g1) / (p2 - p1)
        if abs(slope) < 1e-9:
            continue
        candidate = p1 - g1 / slope
        if candidate <= 0:
            continue
        if seg_hi is not None and not (seg_lo - 1e-9 <= candidate <= seg_hi + 1e-9):
            continue
        if abs(margin_at(candidate) - m) > 0.5:
            continue
        exact = candidate
        break

    # Fallback for a root landing exactly on a step boundary, where no open
    # segment contains it: bisect the whole axis when the sign pattern says
    # a crossing exists. Cheap insurance, rarely needed.
    if exact is None:
        lo_b, hi_b = 0.01, 1_000_000.0
        if g(lo_b) <= 0.0 < g(hi_b):
            for _ in range(80):
                mid = (lo_b + hi_b) / 2.0
                if g(mid) <= 0.0:
                    lo_b = mid
                else:
                    hi_b = mid
            exact = hi_b

    if exact is None:
        return {
            "achievable": False,
            "price": None,
            "target_margin": m,
            "reason": (
                f"No sale price reaches a {m:g}% margin with these costs: the "
                "fees and the risk buffer claim a share of every sale that "
                "leaves less than that margin."
            ),
            "check": None,
        }

    price_rounded = math.ceil(exact * 100.0) / 100.0
    raw = outcome_at(price_rounded)
    return {
        "achievable": True,
        "price": round(price_rounded, 2),
        "target_margin": m,
        "reason": None,
        "check": {
            "price": round(price_rounded, 2),
            "profit": round(raw["profit_raw"], 2),
            "margin": round(raw["profit_raw"] / price_rounded * 100.0, 1),
            "fees_cost_total": round(raw["cost_raw"], 2),
            "net_after_fees": round(raw["proceeds_raw"] - raw["cost_raw"], 2),
        },
        "_raw_price": exact,
    }

