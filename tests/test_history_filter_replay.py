"""An uncomputed margin can never be replayed as a verified rule.

Rows saved before commit "history: persist each filter row's provenance" hold
filter rows with no `verified` key — the save dropped it. Some of those rows
still name a `Margin` filter with `verified: true` because the old dict never
carried anything else, even though no supplier price was read and the margin is
a 0.0 placeholder (C1).

History cannot re-run the analysis, but it can check that one row against the
verdict it belongs to: if the profit was not computed, the margin was not
verified either. The correction is served, not stored.
"""

import pytest


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    import db.models  # noqa: F401 - registers every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    factory = _fresh_session_factory(tmp_path)
    monkeypatch.setattr("db.database.SessionLocal", factory)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as test_client:
        yield test_client, factory


def _saved_verdict(factory, *, profit, profit_computed, filters):
    from db.models import Product, Verdict

    session = factory()
    try:
        product = Product(
            ebay_url="https://www.ebay.co.uk/itm/3001",
            ebay_listing_id="3001",
            title="Stainless Steel Water Bottle",
            price=12.5,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        session.add(
            Verdict(
                product_id=product.id,
                verdict="fail",
                profit_amount=profit,
                profit_margin=0.0,
                profit_computed=profit_computed,
                filter_results=filters,
            )
        )
        session.commit()
        return product.id
    finally:
        session.close()


def _margin_row(**overrides):
    row = {
        "name": "Margin",
        "passed": False,
        "actual": "0.0%",
        "expected": "≥25%",
        "verified": True,
    }
    row.update(overrides)
    return row


def _stored_filters(factory, product_id):
    from db.models import Verdict

    session = factory()
    try:
        return session.query(Verdict).filter(Verdict.product_id == product_id).one().filter_results
    finally:
        session.close()


class TestAnUncomputedMarginIsServedUnverified:
    def test_the_stored_true_is_corrected_on_the_way_out(self, client):
        test_client, factory = client
        product_id = _saved_verdict(
            factory, profit=0.0, profit_computed=None, filters=[_margin_row()]
        )

        detail = test_client.get(f"/api/history/{product_id}").json()
        row = detail["verdict"]["filter_results"][0]

        assert detail["profit_computed"] is False
        assert row["verified"] is False

    def test_the_stored_row_is_not_rewritten(self, client):
        """A replay is a reading, not a migration of old evidence."""
        test_client, factory = client
        product_id = _saved_verdict(
            factory, profit=0.0, profit_computed=None, filters=[_margin_row()]
        )

        test_client.get(f"/api/history/{product_id}")

        assert _stored_filters(factory, product_id)[0]["verified"] is True

    def test_a_computed_margin_keeps_its_verified_mark(self, client):
        test_client, factory = client
        product_id = _saved_verdict(
            factory,
            profit=3.2,
            profit_computed=True,
            filters=[_margin_row(passed=True, actual="25.6%")],
        )

        detail = test_client.get(f"/api/history/{product_id}").json()
        row = detail["verdict"]["filter_results"][0]

        assert detail["profit_computed"] is True
        assert row["verified"] is True

    def test_a_legacy_computed_figure_keeps_its_verified_mark(self, client):
        """A non-zero profit among pre-flag rows was necessarily calculated."""
        test_client, factory = client
        product_id = _saved_verdict(
            factory,
            profit=-1.1,
            profit_computed=None,
            filters=[_margin_row()],
        )

        detail = test_client.get(f"/api/history/{product_id}").json()
        assert detail["profit_computed"] is True
        assert detail["verdict"]["filter_results"][0]["verified"] is True

    def test_other_rows_are_left_exactly_as_stored(self, client):
        test_client, factory = client
        product_id = _saved_verdict(
            factory,
            profit=0.0,
            profit_computed=None,
            filters=[
                _margin_row(),
                {
                    "name": "Demand (7d)",
                    "passed": False,
                    "actual": "0 sold",
                    "expected": "≥1 sold",
                    "verified": False,
                },
            ],
        )

        detail = test_client.get(f"/api/history/{product_id}").json()
        margin, demand = detail["verdict"]["filter_results"]

        assert margin["verified"] is False
        assert demand == {
            "name": "Demand (7d)",
            "passed": False,
            "actual": "0 sold",
            "expected": "≥1 sold",
            "verified": False,
        }
