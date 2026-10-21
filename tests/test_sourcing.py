"""Tests for the shared sourcing policy."""

from dataclasses import dataclass, field
from typing import Optional

from engine.sourcing import (
    SOURCING_POLICY_VERSION,
    assess_supplier,
    apply_assessment,
    rank_suppliers,
    apply_ranking,
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
    seller_rating: str = "4.8 (120 reviews)"
    review_rating: Optional[float] = None
    review_count: Optional[int] = None
    standard_shipping_available: Optional[bool] = None
    standard_shipping_cost: Optional[float] = None
    standard_shipping_days_min: Optional[int] = None
    standard_shipping_days_max: Optional[int] = None
    standard_shipping_raw: str = ""


def test_missing_price_is_not_preferred():
    product = Supplier(price=0.0)
    assessment = assess_supplier(product)
    assert assessment.preferred is False
    assert assessment.eligible is False
    assert "product price not read" in assessment.reasons


def test_missing_stock_is_not_treated_as_in_stock():
    product = Supplier(in_stock="", stock_raw="")
    assessment = assess_supplier(product)
    assert assessment.preferred is False
    assert assessment.stock_verified is False
    assert "stock status not verified" in assessment.reasons


def test_out_of_stock_is_not_preferred():
    product = Supplier(in_stock="out_of_stock", stock_raw="Out of stock")
    assessment = assess_supplier(product)
    assert assessment.preferred is False
    assert "out of stock" in assessment.reasons


def test_unknown_shipping_is_not_treated_as_free():
    product = Supplier(shipping_cost=0.0, shipping_raw="delivery in 3 days")
    assessment = assess_supplier(product)
    assert assessment.shipping_known is False
    assert assessment.total_landed_cost is None
    assert assessment.preferred is False
    assert "shipping cost not read" in assessment.reasons


def test_known_free_shipping_is_recognised():
    product = Supplier(shipping_cost=0.0, shipping_raw="Free delivery")
    assessment = assess_supplier(product)
    assert assessment.shipping_known is True
    assert assessment.shipping_cost == 0.0
    assert assessment.total_landed_cost == 10.0


def test_aliexpress_without_standard_shipping_is_not_preferred():
    product = Supplier(source="AliExpress", standard_shipping_available=False)
    assessment = assess_supplier(product)
    assert assessment.preferred is False
    assert assessment.standard_shipping_applicable is True
    assert "AliExpress Standard Shipping unavailable" in assessment.reasons


def test_aliexpress_with_unverified_standard_shipping_is_not_preferred():
    product = Supplier(source="AliExpress", standard_shipping_available=None)
    assessment = assess_supplier(product)
    assert assessment.preferred is False
    assert "AliExpress Standard Shipping not verified" in assessment.reasons


def test_aliexpress_with_standard_shipping_is_eligible():
    product = Supplier(
        source="AliExpress",
        standard_shipping_available=True,
        standard_shipping_cost=3.2,
        standard_shipping_days_min=8,
        standard_shipping_days_max=15,
    )
    assessment = assess_supplier(product)
    assert assessment.preferred is True
    assert assessment.standard_shipping_applicable is True
    assert assessment.total_landed_cost == 13.2


def test_review_missing_is_not_perfect():
    product = Supplier(seller_rating="")
    assessment = assess_supplier(product)
    assert assessment.review_verified is False
    assert assessment.review_good is False
    assert assessment.sourcing_score < 100.0
    assert "review rating not read" in assessment.reasons


def test_review_below_threshold_is_reported():
    product = Supplier(seller_rating="3.2 (10 reviews)")
    assessment = assess_supplier(product)
    assert assessment.review_verified is True
    assert assessment.review_good is False
    assert "review rating below preferred threshold" in assessment.reasons


def test_total_landed_cost_prefers_cheaper_shipping():
    cheap = Supplier(price=10.0, shipping_cost=5.0, shipping_raw="GBP 5.00 delivery")
    expensive = Supplier(price=9.0, shipping_cost=7.0, shipping_raw="GBP 7.00 delivery")
    ranked = rank_suppliers([expensive, cheap])
    assert ranked[0][0] is cheap


def test_good_review_ranks_above_unverified_review_at_similar_cost():
    good = Supplier(price=10.0, shipping_cost=2.0, shipping_raw="GBP 2.00 delivery", seller_rating="4.8 (100 reviews)")
    unknown = Supplier(price=10.0, shipping_cost=2.0, shipping_raw="GBP 2.00 delivery", seller_rating="")
    ranked = rank_suppliers([unknown, good])
    assert ranked[0][0] is good


def test_apply_assessment_writes_fields():
    product = Supplier()
    assessment = assess_supplier(product)
    apply_assessment(product, assessment)
    assert product.sourcing_preferred is True
    assert product.sourcing_reasons == []
    assert product.total_landed_cost == 12.0
    assert product.sourcing_policy_version == SOURCING_POLICY_VERSION


def test_apply_assessment_writes_mapping():
    product = {"price": 10.0, "shipping_cost": 2.0, "shipping_raw": "GBP 2.00 delivery", "in_stock": "in_stock", "url": "https://example.com", "verified": True, "match_tier": "verified"}
    assessment = assess_supplier(product)
    apply_assessment(product, assessment)
    assert product["sourcing_preferred"] is True
    assert product["total_landed_cost"] == 12.0
    assert product["sourcing_policy_version"] == SOURCING_POLICY_VERSION
