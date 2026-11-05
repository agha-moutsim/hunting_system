"""History must not print the verdict engine's 0.0 placeholder as £0.00.

C1: a figure nobody computed is absent. The engine starts from
``{"profit": 0.0, "margin": 0.0}`` and only replaces it when a supplier price
was read (engine/decisions.py); the pipeline stores that default. Newer runs
record ``profit_computed``, and both History endpoints serve null when it is
false. A genuine zero recorded by such a run stays a number.
"""

import pytest


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    import db.models  # noqa: F401 - registers every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def history_client(tmp_path, monkeypatch):
    factory = _fresh_session_factory(tmp_path)
    monkeypatch.setattr("db.database.SessionLocal", factory)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        yield client, factory


def _saved_analysis(
    factory,
    *,
    listing_id,
    profit,
    supplier_prices=(),
    profit_computed=None,
):
    """One saved product + verdict, with the supplier rows it was saved with."""
    from db.models import Product, SupplierMatch, Verdict

    session = factory()
    try:
        product = Product(
            ebay_url=f"https://www.ebay.co.uk/itm/{listing_id}",
            ebay_listing_id=listing_id,
            title="Stainless Steel Water Bottle",
            price=12.5,
        )
        session.add(product)
        session.commit()
        session.refresh(product)

        for index, price in enumerate(supplier_prices):
            session.add(
                SupplierMatch(
                    product_id=product.id,
                    supplier_name=f"supplier-{index}",
                    supplier_price=price,
                )
            )
        session.add(
            Verdict(
                product_id=product.id,
                verdict="fail",
                profit_amount=profit,
                profit_margin=0.0,
                profit_computed=profit_computed,
            )
        )
        session.commit()
        return product.id
    finally:
        session.close()


class TestHistoryProfitProvenance:
    def test_a_zero_with_no_supplier_price_is_served_as_absent(
        self, history_client
    ):
        client, factory = history_client
        product_id = _saved_analysis(factory, listing_id="1001", profit=0.0)

        row = client.get("/api/history").json()["products"][0]
        assert row["profit_computed"] is False
        assert row["profit"] is None
        assert row["margin"] is None

        detail = client.get(f"/api/history/{product_id}").json()
        assert detail["profit_computed"] is False
        assert detail["verdict"]["profit_amount"] is None
        assert detail["verdict"]["profit_margin"] is None

    def test_a_zero_recorded_as_computed_is_a_real_zero(self, history_client):
        client, factory = history_client
        product_id = _saved_analysis(
            factory,
            listing_id="1002",
            profit=0.0,
            supplier_prices=(7.64,),
            profit_computed=True,
        )

        row = client.get("/api/history").json()["products"][0]
        assert row["profit_computed"] is True
        assert row["profit"] == 0.0
        assert row["margin"] == 0.0

        detail = client.get(f"/api/history/{product_id}").json()
        assert detail["profit_computed"] is True
        assert detail["verdict"]["profit_amount"] == 0.0
        assert detail["verdict"]["profit_margin"] == 0.0

    def test_a_legacy_zero_beside_suppliers_is_still_not_attributed(
        self, history_client
    ):
        """Suppliers can be added by a later run. They do not prove the saved
        verdict's zero was calculated, so an unrecorded zero stays absent."""
        client, factory = history_client
        product_id = _saved_analysis(
            factory, listing_id="1003", profit=0.0, supplier_prices=(7.64, 11.74)
        )

        row = client.get("/api/history").json()["products"][0]
        assert row["profit_computed"] is False
        assert row["profit"] is None

        detail = client.get(f"/api/history/{product_id}").json()
        assert detail["profit_computed"] is False
        assert detail["verdict"]["profit_amount"] is None

    def test_a_legacy_nonzero_figure_is_kept(self, history_client):
        """A non-zero figure among pre-flag rows must have been calculated."""
        client, factory = history_client
        product_id = _saved_analysis(factory, listing_id="1004", profit=-1.1)

        row = client.get("/api/history").json()["products"][0]
        assert row["profit_computed"] is True
        assert row["profit"] == -1.1

        detail = client.get(f"/api/history/{product_id}").json()
        assert detail["profit_computed"] is True
        assert detail["verdict"]["profit_amount"] == -1.1
