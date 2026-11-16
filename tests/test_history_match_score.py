"""History must replay the C14 score the stored supplier row carries.

C14: a supplier row survives an analysis because the matcher scored the pair
and wrote that score down. The detail payload served every other persisted
column and dropped `match_score`, so a replayed row showed a supplier with no
evidence it had been matched at all. 99 of the 209 stored rows in the live
database carry a score; the replay showed none of them.

The absence rules still hold in both directions: an unscored row serves NULL,
and a real 0.0 is a score rather than a placeholder for one (C1).
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
def client_and_factory(tmp_path, monkeypatch):
    factory = _fresh_session_factory(tmp_path)
    monkeypatch.setattr("db.database.SessionLocal", factory)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        yield client, factory


def _saved_product(factory, *, listing_id, scores):
    """One saved product with a supplier row per score, in order."""
    from db.models import Product, SupplierMatch

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

        for index, score in enumerate(scores):
            session.add(
                SupplierMatch(
                    product_id=product.id,
                    supplier_name=f"supplier-{index}",
                    supplier_price=7.64,
                    match_score=score,
                )
            )
        session.commit()
        return product.id
    finally:
        session.close()


class TestHistoryMatchScore:
    def test_a_stored_score_is_served_with_its_row(self, client_and_factory):
        client, factory = client_and_factory
        product_id = _saved_product(
            factory, listing_id="2001", scores=[0.5885, 0.41]
        )

        body = client.get(f"/api/history/{product_id}").json()

        assert [row["match_score"] for row in body["suppliers"]] == [0.5885, 0.41]

    def test_an_unscored_row_serves_no_score(self, client_and_factory):
        # The matcher never scored this row. NULL is the stored answer, and a
        # 0.0 here would read as a real (lowest possible) score.
        client, factory = client_and_factory
        product_id = _saved_product(factory, listing_id="2002", scores=[None])

        body = client.get(f"/api/history/{product_id}").json()

        assert body["suppliers"][0]["match_score"] is None

    def test_a_zero_score_is_a_score(self, client_and_factory):
        client, factory = client_and_factory
        product_id = _saved_product(factory, listing_id="2003", scores=[0.0])

        body = client.get(f"/api/history/{product_id}").json()

        assert body["suppliers"][0]["match_score"] == 0.0
