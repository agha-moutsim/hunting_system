"""Sourcing fields must survive the journey to the database."""

import pytest

from scrapers.base import ScrapedProduct

pytestmark = pytest.mark.usefixtures("_no_live_db")


@pytest.fixture
def _no_live_db(monkeypatch):
    import analysis_pipeline as ap

    saved: list[dict] = []
    monkeypatch.setattr(
        ap, "save_supplier_match_data", lambda db, product_id, data: saved.append(data)
    )
    return saved


def _results(*suppliers):
    return {
        "ebay_product": ScrapedProduct(
            source="ebay_uk", title="Greenhouse 6ft", price=30.0,
            url="https://www.ebay.co.uk/itm/1", condition="New", verified=True,
        ),
        "demand": None,
        "supplier_matches": list(suppliers),
        "llm_analysis": None,
        "verdict": None,
    }


def _supplier(**overrides):
    supplier = ScrapedProduct(
        source="AliExpress", title="6ft Greenhouse", price=9.4,
        url="https://www.aliexpress.com/item/1", condition="New", verified=True,
    )
    supplier.match_score = 0.82
    supplier.match_tier = "verified"
    supplier.in_stock = "in_stock"
    supplier.stock_raw = "In stock"
    supplier.shipping_cost = 3.2
    supplier.shipping_raw = "GBP 3.20 delivery"
    supplier.shipping_days = 15
    supplier.review_rating = 4.8
    supplier.review_count = 120
    supplier.review_verified = True
    supplier.review_source = "seller_rating"
    supplier.shipping_methods = ["AliExpress Standard Shipping"]
    supplier.standard_shipping_available = True
    supplier.standard_shipping_cost = 3.2
    supplier.standard_shipping_days_min = 8
    supplier.standard_shipping_days_max = 15
    supplier.standard_shipping_raw = "AliExpress Standard Shipping £3.20 8-15 days"
    supplier.total_landed_cost = 12.6
    supplier.sourcing_preferred = True
    supplier.sourcing_eligible = True
    supplier.sourcing_reasons = []
    supplier.sourcing_score = 87.5
    supplier.sourcing_policy_version = "sourcing-policy-v1"
    for key, value in overrides.items():
        setattr(supplier, key, value)
    return supplier


class TestSourcingFieldsArePersisted:
    def test_real_sourcing_evidence_reaches_the_database(self, _no_live_db):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier()))

        row = _no_live_db[0]
        assert row["review_rating"] == 4.8
        assert row["review_count"] == 120
        assert row["review_verified"] is True
        assert row["review_source"] == "seller_rating"
        assert row["stock_status"] == "in_stock"
        assert row["stock_verified"] is True
        assert row["shipping_known"] is True
        assert row["shipping_methods"] == ["AliExpress Standard Shipping"]
        assert row["standard_shipping_available"] is True
        assert row["standard_shipping_cost"] == 3.2
        assert row["standard_shipping_days_min"] == 8
        assert row["standard_shipping_days_max"] == 15
        assert row["total_landed_cost"] == 12.6
        assert row["sourcing_preferred"] is True
        assert row["sourcing_eligible"] is True
        assert row["sourcing_reasons"] == []
        assert row["sourcing_score"] == 87.5
        assert row["sourcing_policy_version"] == "sourcing-policy-v1"

    def test_missing_sourcing_evidence_stays_null(self, _no_live_db):
        import analysis_pipeline as ap

        supplier = _supplier(
            review_rating=None,
            review_count=None,
            review_verified=False,
            review_source="",
            stock_status="",
            stock_verified=False,
            shipping_known=False,
            shipping_methods=[],
            standard_shipping_available=None,
            standard_shipping_cost=None,
            standard_shipping_days_min=None,
            standard_shipping_days_max=None,
            standard_shipping_raw="",
            total_landed_cost=None,
            sourcing_preferred=False,
            sourcing_eligible=False,
            sourcing_reasons=["stock status not verified"],
            sourcing_score=0.0,
            sourcing_policy_version="",
        )
        ap.save_analysis_to_db(_results(supplier))

        row = _no_live_db[0]
        assert row["review_rating"] is None
        assert row["review_count"] is None
        assert row["standard_shipping_available"] is None
        assert row["standard_shipping_cost"] is None
        assert row["total_landed_cost"] is None
        assert row["sourcing_reasons"] == ["stock status not verified"]