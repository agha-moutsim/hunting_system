"""Tests for AliExpress sourcing evidence extraction."""

from scrapers.aliexpress import AliExpressScraper


def test_standard_shipping_is_read_when_present():
    available, cost, minimum, maximum, raw = (
        AliExpressScraper._read_aliexpress_standard_shipping(
            "AliExpress Standard Shipping £3.20 8-15 days"
        )
    )
    assert available is True
    assert cost == 3.2
    assert minimum == 8
    assert maximum == 15
    assert "Standard Shipping" in raw


def test_standard_shipping_free_is_not_unknown():
    available, cost, minimum, maximum, raw = (
        AliExpressScraper._read_aliexpress_standard_shipping(
            "AliExpress Standard Shipping Free 10-20 days"
        )
    )
    assert available is True
    assert cost == 0.0
    assert minimum == 10
    assert maximum == 20
    assert raw


def test_standard_shipping_unavailable_is_flagged():
    available, cost, minimum, maximum, raw = (
        AliExpressScraper._read_aliexpress_standard_shipping(
            "Standard Shipping unavailable; ePacket £1.99"
        )
    )
    assert available is False
    assert cost is None
    assert minimum is None
    assert maximum is None
    assert "unavailable" in raw.lower()


def test_standard_shipping_is_unknown_when_not_stated():
    available, cost, minimum, maximum, raw = (
        AliExpressScraper._read_aliexpress_standard_shipping(
            "ePacket £1.99 10-20 days"
        )
    )
    assert available is None
    assert cost is None
    assert minimum is None
    assert maximum is None
    assert raw == ""


def test_review_rating_and_count_are_parsed():
    rating, count, verified = AliExpressScraper._parse_review_text(
        "4.8 (1,234 reviews)"
    )
    assert rating == 4.8
    assert count == 1234
    assert verified is True


def test_review_percentage_is_not_treated_as_a_rating():
    rating, count, verified = AliExpressScraper._parse_review_text(
        "98% (1,234 orders)"
    )
    assert rating is None
    assert count is None
    assert verified is False


def test_shipping_methods_are_read_from_text():
    methods = AliExpressScraper._shipping_methods(
        "AliExpress Standard Shipping £3.20, ePacket £1.99"
    )
    assert methods == ["AliExpress Standard Shipping", "ePacket"]