"""Consistency and edge-case tests for the shared sourcing policy."""

from dataclasses import dataclass, field
from typing import Optional

from engine.sourcing import (
    SOURCING_POLICY_VERSION,
    apply_ranking,
    assess_supplier,
)


@dataclass
class Supplier:
    source: str = "Test Supplier"
    title: str = "cordless drill 18v"
    price: float = 10.0
    url: str = "https://example.com/item"
    verified: bool = True
    match_tier: str = "verified"
    match_score: float = 0.9
    in_stock: str = "in_stock"
    stock_raw: str = "In stock"
    shipping_cost: float = 2.0
    shipping_raw: str = "GBP 2.00 delivery"
    shipping_days: int = 3
    seller_rating: str = "4.8 (100 reviews)"
    review_rating: Optional[float] = None
    review_count: Optional[int] = None
    standard_shipping_available: Optional[bool] = None
    standard_shipping_cost: Optional[float] = None
    standard_shipping_days_min: Optional[int] = None
    standard_shipping_days_max: Optional[int] = None
    standard_shipping_raw: str = ""
    shipping_methods: list[str] = field(default_factory=list)


def test_ranking_is_deterministic():
    suppliers = [
        Supplier(price=12.0, shipping_cost=3.0, shipping_raw="GBP 3.00 delivery"),
        Supplier(price=10.0, shipping_cost=4.0, shipping_raw="GBP 4.00 delivery"),
        Supplier(price=11.0, shipping_cost=2.0, shipping_raw="GBP 2.00 delivery"),
    ]
    first = [p.source for p in apply_ranking(suppliers, "GB")]
    second = [p.source for p in apply_ranking(suppliers, "GB")]
    assert first == second


def test_total_landed_cost_beats_product_price():
    cheap_total = Supplier(
        price=12.0, shipping_cost=1.0, shipping_raw="GBP 1.00 delivery"
    )
    expensive_total = Supplier(
        price=9.0, shipping_cost=6.0, shipping_raw="GBP 6.00 delivery"
    )
    ranked = apply_ranking([expensive_total, cheap_total], "GB")
    assert ranked[0] is cheap_total
    assert ranked[0].total_landed_cost == 13.0


def test_missing_shipping_is_not_preferred():
    supplier = Supplier(shipping_cost=0.0, shipping_raw="delivery in 3 days")
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert assessment.shipping_known is False
    assert "shipping cost not read" in assessment.reasons


def test_unknown_stock_is_not_treated_as_available():
    supplier = Supplier(in_stock="", stock_raw="")
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert assessment.stock_verified is False
    assert "stock status not verified" in assessment.reasons


def test_out_of_stock_is_not_preferred():
    supplier = Supplier(in_stock="out_of_stock", stock_raw="Out of stock")
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert "out of stock" in assessment.reasons


def test_aliexpress_standard_shipping_unavailable_is_not_preferred():
    supplier = Supplier(
        source="AliExpress",
        standard_shipping_available=False,
        standard_shipping_raw="Standard Shipping unavailable",
    )
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert "AliExpress Standard Shipping unavailable" in assessment.reasons


def test_aliexpress_unverified_standard_shipping_is_not_preferred():
    supplier = Supplier(source="AliExpress", standard_shipping_available=None)
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert "AliExpress Standard Shipping not verified" in assessment.reasons


def test_missing_review_does_not_claim_perfect_score():
    supplier = Supplier(seller_rating="")
    assessment = assess_supplier(supplier)
    assert assessment.review_verified is False
    assert assessment.sourcing_score < 100.0
    assert "review rating not read" in assessment.reasons


def test_missing_review_count_is_reported():
    supplier = Supplier(seller_rating="4.8")
    assessment = assess_supplier(supplier)
    assert assessment.review_verified is True
    assert assessment.review_good is False
    assert "review count not read" in assessment.reasons


def test_zero_shipping_raw_is_unknown_not_free():
    supplier = Supplier(shipping_cost=0.0, shipping_raw="")
    assessment = assess_supplier(supplier)
    assert assessment.shipping_known is False
    assert assessment.total_landed_cost is None


def test_preferred_requires_verified_listing_url():
    supplier = Supplier(url="not-a-url")
    assessment = assess_supplier(supplier)
    assert assessment.preferred is False
    assert "verified listing URL missing" in assessment.reasons


def test_assessment_policy_version_is_stamped():
    supplier = Supplier()
    assessment = assess_supplier(supplier)
    assert assessment.policy_version == SOURCING_POLICY_VERSION
    assert assessment.sourcing_score >= 0.0


def test_apply_ranking_preserves_supplier_count():
    suppliers = [Supplier(price=10.0), Supplier(price=12.0)]
    ranked = apply_ranking(suppliers, "GB")
    assert len(ranked) == 2
    assert all(hasattr(p, "sourcing_preferred") for p in ranked)
