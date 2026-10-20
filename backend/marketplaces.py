"""The marketplace registry, read through one validated door.

Phase J. `config.MARKETPLACES` is the data; this module is the only reader.
Keeping the lookup here means a route, a scraper and the UI cannot disagree
about which currency a market uses, which site host it searches, or whether a
fee table exists for it.

The rules this module exists to make hard to break:

  * an unknown marketplace is refused, never silently treated as EBAY_GB;
  * only markets whose deals URL was observed reachable are offered;
  * a market without a fee table has no fee table. We do not fall back to the
    UK card, because a GBP rate applied to a USD sale is a fabricated number.

Absent is stated. `fee_table` is None for every non-UK market, and
`fee_warning` carries the sentence a surface must show instead of a price.
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


def fee_warning(market: dict) -> Optional[str]:
    """Why this market cannot be priced, or None for the UK.

    The wording is shared by the API, the fee calculator and the header so a
    user never sees a UK fee figure under a USD heading without being told.
    """
    if market.get("fee_table"):
        return None
    return (
        f"Fee tables are UK-only. No {market['currency']} fee table is "
        f"registered for {market['label']}, so fee and profit figures are "
        "not calculated for this marketplace."
    )


def public_marketplace(market: dict) -> dict:
    """One market as the API/UI should see it. No credentials live here."""
    return {
        "id": market["id"],
        "label": market["label"],
        "country_code": market["country_code"],
        "currency": market["currency"],
        "currency_symbol": market["currency_symbol"],
        "fee_table": market.get("fee_table"),
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
