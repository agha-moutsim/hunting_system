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
  * a registered card is not the same as an enabled calculator. EBAY_AU
    carries its sourced card key, but `fee_calculator_ready` stays False until
    the AU seller defaults and unlock land. The public `fee_table` remains
    None until then, so a surface cannot mistake "card on file" for "ready to
    price".

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
    """Whether this market may be priced today.

    A fee table alone is not enough. The AU card is registered and sourced,
    but its calculator switch stays off until Phase E5 wires the AU seller
    defaults into every pricing surface. Keeping the switch separate means
    adding a card can never silently expose a calculator that still assumes
    the UK branch.
    """
    return bool(market.get("fee_table")) and bool(
        market.get("fee_calculator_ready")
    )


def fee_warning(market: dict) -> Optional[str]:
    """Why this market cannot be priced, or None when it can.

    The wording is shared by the API, the fee calculator and the header so a
    user never sees a UK fee figure under a USD/AUD heading without being told.
    A registered-but-locked card is named rather than hidden: the card exists,
    the calculator is simply not enabled yet.
    """
    if fee_calculator_ready(market):
        return None
    table = market.get("fee_table")
    if table:
        return (
            f"The {market['label']} fee card ({table}) is registered, but the "
            f"fee calculator is not enabled for this marketplace yet, so no "
            f"{market['currency']} fee or profit figure is calculated."
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
