"""Phase C - the AU market's config, defaults and currency boundary.

The AU fee card exists and is registered, but its calculator stays locked
until Phase E5. These pins keep the two states apart:

  * the registry carries the AU card key, while the public record reports no
    usable table and a sentence saying why;
  * the seller-side defaults are the AU branch (Individual, domestic AU), not
    the UK business branch copied across;
  * a card is never applied across currencies, even when a caller names one
    explicitly;
  * the supplier-comparison surfaces still say UK-only without claiming the
    fee card is UK-only too.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.fees import _market_table, _seller_side
from api.market_context import require_uk_market
from api.schemas import FeeCalculateRequest
from marketplaces import (
    fee_calculator_ready,
    fee_warning,
    get_marketplace,
    seller_defaults,
)


class TestTheRegisteredCardIsNotAReadyCalculator:
    def test_au_has_the_card_but_the_public_record_withholds_it(self):
        au = get_marketplace("EBAY_AU")
        assert au["fee_table"] == "au-rate-card-2026-10-09"
        assert fee_calculator_ready(au) is False
        warning = fee_warning(au)
        assert "au-rate-card-2026-10-09" in warning
        assert "not enabled" in warning

    def test_the_public_selector_cannot_offer_the_locked_card(self):
        from marketplaces import public_marketplace

        public = public_marketplace(get_marketplace("EBAY_AU"))
        assert public["fee_table"] is None
        assert public["fee_table_registered"] == "au-rate-card-2026-10-09"
        assert public["fee_calculator_ready"] is False
        assert public["seller_defaults"]["seller_type"] == "private"


class TestTheSellerSideStartsFromTheMarket:
    def test_au_defaults_to_individual_domestic_and_aud(self):
        au = get_marketplace("EBAY_AU")
        side = _seller_side(FeeCalculateRequest(sale_price=10.0), au)
        assert side["seller_type"] == "private"
        assert side["seller_plan"] is None
        assert side["buyer_region"] == "au"
        assert side["fee_table"] == "au-rate-card-2026-10-09"

    def test_au_business_materialises_pro_starter(self):
        au = get_marketplace("EBAY_AU")
        side = _seller_side(
            FeeCalculateRequest(sale_price=10.0, seller_type="business"), au
        )
        assert side["seller_type"] == "business"
        assert side["seller_plan"] == "starter"

    def test_uk_keeps_its_own_branch(self):
        uk = get_marketplace("EBAY_GB")
        side = _seller_side(FeeCalculateRequest(sale_price=10.0), uk)
        assert side["seller_type"] == "business"
        assert side["buyer_region"] == "uk"
        assert side["fee_table"] == "uk-rate-card-2026-09-30"

    def test_an_explicit_market_field_wins(self):
        au = get_marketplace("EBAY_AU")
        side = _seller_side(
            FeeCalculateRequest(sale_price=10.0, buyer_region="uk"), au
        )
        assert side["buyer_region"] == "uk"


class TestTheCurrencyBoundary:
    def test_the_uk_market_uses_the_uk_card_by_default(self):
        uk = get_marketplace("EBAY_GB")
        table = _market_table(uk)
        assert table["key"] == "uk-rate-card-2026-09-30"
        assert table["currency"] == "GBP"

    def test_a_foreign_card_is_refused(self):
        uk = get_marketplace("EBAY_GB")
        with pytest.raises(HTTPException) as exc:
            _market_table(uk, "au-rate-card-2026-10-09")
        assert exc.value.status_code == 422
        assert "AUD" in exc.value.detail
        assert "GBP" in exc.value.detail

    def test_a_market_with_no_card_never_falls_through_to_the_active_uk_card(self):
        us = get_marketplace("EBAY_US")
        with pytest.raises(HTTPException) as exc:
            _market_table(us)
        assert exc.value.status_code == 422
        assert "No USD fee table" in exc.value.detail


class TestTheSupplierSurfacesStayUKOnly:
    def test_the_message_names_the_gbp_bench_not_a_uk_only_fee_card(self):
        au = get_marketplace("EBAY_AU")
        with pytest.raises(HTTPException) as exc:
            require_uk_market(au, "Deep Search")
        detail = exc.value.detail
        assert "UK-only" in detail
        assert "GBP supplier costs" in detail
        assert "UK fee table" not in detail
