"""History rows now carry their own marketplace and currency."""


from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.queries import get_recent_products, save_product
from scrapers.base import ScrapedProduct


OLD_PRODUCTS = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebay_url TEXT NOT NULL,
    ebay_listing_id VARCHAR(64),
    title TEXT,
    price FLOAT,
    condition VARCHAR(32),
    format VARCHAR(32),
    seller VARCHAR(128),
    image_url TEXT,
    category VARCHAR(128),
    created_at DATETIME,
    updated_at DATETIME
)
"""


@pytest.fixture()
def old_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(OLD_PRODUCTS))
        conn.execute(
            text(
                "INSERT INTO products (ebay_url, title, price) "
                "VALUES ('https://example.com/item', 'Widget', 12.5)"
            )
        )
    monkeypatch.setattr(dbmod, "engine", engine)
    return engine


def _cols(engine):
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(products)")).fetchall()
    return {r[1] for r in rows}


class TestProductSchemaMigration:
    def test_missing_columns_are_added(self, old_db):
        from db.database import ensure_product_columns

        added = ensure_product_columns()

        assert set(added) == {"marketplace", "currency"}
        assert {"marketplace", "currency"} <= _cols(old_db)

    def test_a_second_run_adds_nothing(self, old_db):
        from db.database import ensure_product_columns

        ensure_product_columns()
        assert ensure_product_columns() == []

    def test_existing_rows_survive_with_uk_defaults(self, old_db):
        from db.database import ensure_product_columns

        ensure_product_columns()

        with old_db.connect() as conn:
            row = conn.execute(
                text("SELECT marketplace, currency FROM products")
            ).fetchone()
        assert row == ("EBAY_GB", "GBP")


class TestProductPersistenceCarriesMarket:
    def test_save_product_stores_marketplace_and_currency(self, tmp_path, monkeypatch):
        engine = create_engine(f"sqlite:///{tmp_path/'new.db'}")
        Base.metadata.create_all(engine)
        monkeypatch.setattr(dbmod, "engine", engine)
        session_factory = sessionmaker(bind=engine)
        monkeypatch.setattr(dbmod, "SessionLocal", session_factory)

        from db.database import ensure_product_columns

        ensure_product_columns()

        db = session_factory()
        try:
            product = ScrapedProduct(
                source="ebay_au",
                title="Widget",
                price=12.5,
                url="https://example.com/au-item",
            )
            product_id = save_product(
                db, product, marketplace="EBAY_AU", currency="AUD"
            )
            rows = get_recent_products(db, limit=10)
        finally:
            db.close()

        assert any(row["id"] == product_id for row in rows)
        saved = next(row for row in rows if row["id"] == product_id)
        assert saved["marketplace"] == "EBAY_AU"
        assert saved["currency"] == "AUD"

    def test_the_detail_payload_carries_the_same_market_and_currency(
        self, tmp_path, monkeypatch
    ):
        """The list named AUD and the detail re-labelled the same rows £.

        History detail is the screen with the money on it; a stored AUD price
        served without its currency is rendered in pounds by the Scorecard.
        """
        engine = create_engine(f"sqlite:///{tmp_path/'detail.db'}")
        Base.metadata.create_all(engine)
        monkeypatch.setattr(dbmod, "engine", engine)
        session_factory = sessionmaker(bind=engine)
        monkeypatch.setattr(dbmod, "SessionLocal", session_factory)

        from db.database import ensure_product_columns

        ensure_product_columns()

        db = session_factory()
        try:
            product = ScrapedProduct(
                source="ebay_au",
                title="Widget",
                price=12.5,
                url="https://example.com/au-item",
            )
            product_id = save_product(
                db, product, marketplace="EBAY_AU", currency="AUD"
            )
        finally:
            db.close()

        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            detail = client.get(f"/api/history/{product_id}").json()

        assert detail["product"]["marketplace"] == "EBAY_AU"
        assert detail["product"]["currency"] == "AUD"