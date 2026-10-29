"""The marketplace registry, read through one validated door.

Phase J. `config.MARKETPLACES` is the data; this module is the only reader.
Keeping the lookup here means a route, a scraper and the UI cannot disagree
about which currency a market uses, which site host it searches, or whether a
fee table exists for it.

The rules this module exists to make hard to break:

  * an unknown marketplace is refused, never silently treated as EBAY_GB;
  * only markets whose deals URL was observed reachable are offered;
  * a market without a fee table has no fee table. We do not fall back to the
    UK card, because a GBP rate applied to a USD sale is a fabricated number;
  * a registered card is not automatically an enabled calculator. A market
    may carry a sourced card while `fee_calculator_ready` is still False; the
    public `fee_table` stays None until the switch is on, so a surface cannot
    mistake "card on file" for "ready to price". EBAY_AU's switch was turned
    on in Phase E5, when its AUD calculator surface was ready.

Absent is stated. `fee_warning` carries the sentence a surface must show
instead of a price, and `fee_table_registered` names a card that exists but is
not yet usable without pretending it is ready.
"""

from __future__ import annotations

from typing import Optional

from config import DEFAULT_MARKETPLACE, MARKETPLACES

#: Header the browser sends on every API call. A query parameter with the same
#: name is also accepted so curl and tests can ask for a market without a
#: browser. The query value wins when both are present.
MARKETPLACE_HEADER = "X-EBay-Marketplace"
MARKETPLACE_QUERY = "marketplace"


class UnknownMarketplace(ValueError):
    """A marketplace id the registry does not carry."""


def marketplace_ids() -> tuple[str, ...]:
    """Every registered id, in registry order."""
    return tuple(MARKETPLACES)


def get_marketplace(marketplace: Optional[str] = None) -> dict:
    """Return one market record, or refuse an unknown id.

    None/"" means the configured default, which is the historical EBAY_GB
    unless EBAY_MARKETPLACE names another registered market. An explicit
    unknown id raises: falling back to UK here would search the wrong site and
    print the wrong currency without a word.
    """
    market_id = (marketplace or DEFAULT_MARKETPLACE).strip().upper()
    try:
        return MARKETPLACES[market_id]
    except KeyError as exc:
        known = ", ".join(marketplace_ids())
        raise UnknownMarketplace(
            f"unknown marketplace {marketplace!r}; choose one of: {known}"
        ) from exc


def offered_marketplaces() -> list[dict]:
    """The markets the selector may offer.

    `offered` is not a marketing flag. It is set only after that market's deals
    URL was fetched and returned a real 200 (`deals_http_status`), because the
    deals board is marketplace-specific. An unverified market is not offered.
    """
    return [
        public_marketplace(market)
        for market in MARKETPLACES.values()
        if market.get("offered") and market.get("deals_http_status") == 200
    ]


def fee_calculator_ready(market: dict) -> bool:
    """Whether this market's standalone fee calculator may be used today.

    A fee table alone is not enough. The switch is turned on only when the
    market's calculator surface can render its currency, seller branches and
    plan controls. Keeping the switch separate means adding a card can never
    silently expose a calculator that still assumes the UK branch. AU's
    switch was turned on in Phase E5.
    """
    return bool(market.get("fee_table")) and bool(
        market.get("fee_calculator_ready")
    )


SELLER_DEFAULT_FIELDS = (
    "seller_type",
    "buyer_region",
    "seller_plan",
    "uk_resident",
    "vat_registered",
)


def seller_defaults(market: dict) -> dict:
    """The seller-side starting point this market states, not a fee rate.

    These values answer "which branch is this market's calculator in?" rather
    than "what does the seller earn?". A field the market does not state stays
    None so the engine's own card default applies; it is never guessed here.
    The seller's own config.SELLER_PROFILE still wins when a request supplies
    a value.
    """
    raw = market.get("seller_defaults") or {}
    return {field: raw.get(field) for field in SELLER_DEFAULT_FIELDS}


def analyze_ready(market: dict) -> bool:
    """Whether Analyze may run its full sourcing pipeline for this market.

    This is deliberately separate from `fee_calculator_ready`. AU carries a
    sourced fee card and a supplier bench, so its Analyze pipeline can price a
    product and produce a verdict. A market without a card or a bench stays
    search-only: there is nothing honest to compare.
    """
    return bool(
        market.get("analyze_ready")
        and market.get("fee_table")
        and supplier_bench(market)
    )


def market_filter_defaults(market: dict) -> dict:
    """The filter values this market states for its own currency.

    The UK's active range is user-adjustable and lives in the filter store, so
    the UK record states nothing here. AU states its own AUD band and demand
    floors; a missing field is omitted rather than filled from the GBP config.
    """
    values: dict = {}
    band = market.get("price_band") or {}
    if band.get("min") is not None:
        values["price_min"] = band["min"]
    if band.get("max") is not None:
        values["price_max"] = band["max"]
    floors = market.get("demand_floors") or {}
    if floors.get("30d") is not None:
        values["demand_min_30d"] = floors["30d"]
    if floors.get("7d") is not None:
        values["demand_min_7d"] = floors["7d"]
    return values


def supplier_bench(market: dict) -> tuple[str, ...]:
    """The active supplier slugs this market may use.

    This is market policy, not the supplier catalog: a source can exist in
    `suppliers.json` and still be absent here because it is a UK retailer or
    disabled. An absent bench is empty, never the UK bench: carrying B&Q or
    Toolstation into an AUD analysis would mix currencies and markets.
    """
    return tuple(market.get("supplier_bench") or ())


def fee_warning(market: dict) -> Optional[str]:
    """Why this market's standalone fee calculator cannot be used, or None.

    The wording is shared by the API, the fee calculator and the header so a
    user never sees a UK fee figure under a USD/AUD heading without being told.
    A registered-but-locked card is named rather than hidden: the card exists
    and Analyze may use it, while the standalone calculator is not enabled.
    """
    if fee_calculator_ready(market):
        return None
    table = market.get("fee_table")
    if table:
        return (
            f"The {market['label']} fee card ({table}) is registered, but the "
            f"{market['currency']} fee calculator is not enabled for this "
            "marketplace yet. Analyze can use the card for its own verdict; "
            "the standalone calculator and its seller controls stay locked."
        )
    return (
        f"No {market['currency']} fee table is registered for "
        f"{market['label']}, so fee and profit figures are not calculated for "
        "this marketplace."
    )


def public_marketplace(market: dict) -> dict:
    """One market as the API/UI should see it. No credentials live here.

    `fee_table` is the table a surface may price with, so it is None until the
    calculator is ready. `fee_table_registered` reports the card on file; the
    two fields are deliberately distinct.
    """
    ready = fee_calculator_ready(market)
    return {
        "id": market["id"],
        "label": market["label"],
        "country_code": market["country_code"],
        "currency": market["currency"],
        "currency_symbol": market["currency_symbol"],
        "fee_table": market.get("fee_table") if ready else None,
        "fee_table_registered": market.get("fee_table"),
        "fee_calculator_ready": ready,
        "analyze_ready": analyze_ready(market),
        "price_band": market.get("price_band"),
        "demand_floors": market.get("demand_floors"),
        "momentum_1d": market.get("momentum_1d"),
        "seller_defaults": seller_defaults(market),
        "supplier_bench": list(supplier_bench(market)),
        "fee_warning": fee_warning(market),
        "deals_url": market.get("deals_url"),
        "deals_http_status": market.get("deals_http_status"),
        "deals_checked_at": market.get("deals_checked_at"),
    }


def format_money(amount: Optional[float], currency: str) -> str:
    """One amount with its own currency, or '' when the amount is absent.

    This function formats a single amount; it never adds two amounts. A zero
    is a measured zero and stays "£0.00"/"$0.00". None is unread and becomes
    the empty string, never a zero-looking figure.
    """
    if amount is None:
        return ""
    symbol = next(
        (
            market["currency_symbol"]
            for market in MARKETPLACES.values()
            if market["currency"] == currency
        ),
        "",
    )
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {currency}".strip()
