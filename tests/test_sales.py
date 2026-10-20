"""Phase I - own-sales P&L, CSV import and C14 threshold feedback.

The tests pin the rules that make the numbers safe to show:

* every sale is user-declared, and the response says so;
* a missing cost is not zero, so profit and margin stay absent;
* monthly_stats holds one row per calendar month, in different years too;
* CSV import rejects bad rows with a line and a sentence instead of guessing;
* threshold replay reports stored differences and never changes a threshold.

Threshold replay also states its structural limit: rows the C14 matcher
dropped were never stored, so a lower threshold cannot be replayed as though
those outcomes existed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    from db import models  # noqa: F401 - register every table

    engine = create_engine(f"sqlite:///{tmp_path / 'phase-i-api.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def session_factory(tmp_path):
    return _fresh_session_factory(tmp_path)


@pytest.fixture()
def client(session_factory, monkeypatch):
    monkeypatch.setattr("db.database.SessionLocal", session_factory)
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _sale(**overrides) -> dict:
    today = datetime.utcnow().date().isoformat()
    payload = {
        "product_name": "Cordless Drill",
        "category": "Tools",
        "sale_price": 100.0,
        "supplier_cost": 20.0,
        "shipping_cost": 5.0,
        "ebay_fees": 10.0,
        "quantity": 2,
        "sale_date": today,
        "buyer_location": "",
        "notes": "",
    }
    payload.update(overrides)
    return payload


class TestSaleArithmetic:
    def test_create_returns_the_declared_arithmetic_and_label(self, client):
        resp = client.post("/api/sales", json=_sale())

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_declared"] is True
        assert body["profit_is_complete"] is True
        assert body["profit"] == 130.0
        assert body["margin_percent"] == 65.0
        assert body["sale_price"] == 100.0
        assert body["quantity"] == 2

    def test_missing_cost_is_refused_not_treated_as_zero(self, client):
        payload = _sale()
        payload.pop("ebay_fees")

        resp = client.post("/api/sales", json=payload)

        assert resp.status_code == 422
        assert client.get("/api/sales").json()["count"] == 0

    def test_a_stated_zero_cost_is_real_and_accepted(self, client):
        resp = client.post(
            "/api/sales",
            json=_sale(
                sale_price=25.0,
                supplier_cost=0.0,
                shipping_cost=0.0,
                ebay_fees=0.0,
                quantity=1,
            ),
        )

        assert resp.status_code == 200
        assert resp.json()["profit"] == 25.0
        assert resp.json()["margin_percent"] == 100.0

    def test_sale_date_is_required(self, client):
        payload = _sale()
        payload.pop("sale_date")

        assert client.post("/api/sales", json=payload).status_code == 422

    def test_blank_product_name_is_refused(self, client):
        assert client.post("/api/sales", json=_sale(product_name="   ")).status_code == 422

    def test_the_list_carries_the_declaration_on_every_response(self, client):
        client.post("/api/sales", json=_sale())

        body = client.get("/api/sales").json()

        assert body["user_declared"] is True
        assert "not eBay observations" in body["declaration"]
        assert body["sales"][0]["user_declared"] is True


class TestSummary:
    def test_summary_uses_the_picklist_window_and_previous_period(self, session_factory, client):
        from db.models import Sale

        today = datetime.utcnow().date()
        current_day = datetime.combine(today - timedelta(days=1), datetime.min.time())
        previous_day = datetime.combine(today - timedelta(days=35), datetime.min.time())

        session = session_factory()
        try:
            session.add_all(
                [
                    Sale(
                        product_name="Current",
                        sale_price=100.0,
                        supplier_cost=60.0,
                        shipping_cost=0.0,
                        ebay_fees=10.0,
                        profit=30.0,
                        margin_percent=30.0,
                        quantity=1,
                        sale_date=current_day,
                    ),
                    Sale(
                        product_name="Previous",
                        sale_price=80.0,
                        supplier_cost=60.0,
                        shipping_cost=0.0,
                        ebay_fees=0.0,
                        profit=20.0,
                        margin_percent=25.0,
                        quantity=1,
                        sale_date=previous_day,
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/sales/summary?days=30&months=6").json()

        assert body["user_declared"] is True
        assert body["total_revenue"] == 100.0
        assert body["total_profit"] == 30.0
        assert body["avg_margin"] == 30.0
        assert body["total_sales"] == 1
        assert body["total_units"] == 1
        assert body["growth_revenue"] == 25.0
        assert body["growth_profit"] == 50.0
        assert body["profit_is_complete"] is True
        assert len(body["monthly"]) == 6
        assert body["monthly"] == sorted(body["monthly"], key=lambda m: m["month"])

    def test_missing_costs_make_profit_and_margin_absent_with_a_sentence(self, session_factory, client):
        from db.models import Sale

        session = session_factory()
        try:
            session.add(
                Sale(
                    product_name="Incomplete",
                    sale_price=100.0,
                    supplier_cost=None,
                    shipping_cost=0.0,
                    ebay_fees=0.0,
                    profit=None,
                    margin_percent=None,
                    quantity=1,
                    sale_date=datetime.utcnow(),
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/sales/summary?days=30&months=6").json()

        assert body["total_revenue"] == 100.0
        assert body["total_profit"] is None
        assert body["avg_margin"] is None
        assert body["profit_is_complete"] is False
        assert "did not declare every cost" in body["profit_missing_reason"]
        assert body["monthly"][-1]["profit"] is None
        assert body["monthly"][-1]["profit_missing_reason"]

    def test_no_sales_is_a_measured_zero_with_no_claimed_margin(self, client):
        body = client.get("/api/sales/summary?days=30&months=6").json()

        assert body["total_revenue"] == 0.0
        assert body["total_profit"] == 0.0
        assert body["avg_margin"] is None
        assert body["total_sales"] == 0
        assert body["growth_revenue"] is None
        assert body["profit_is_complete"] is True

    def test_an_empty_current_period_does_not_claim_a_100_percent_drop(
        self, session_factory, client
    ):
        from db.models import Sale

        session = session_factory()
        try:
            session.add(
                Sale(
                    product_name="Previous only",
                    sale_price=80.0,
                    supplier_cost=60.0,
                    shipping_cost=0.0,
                    ebay_fees=0.0,
                    profit=20.0,
                    margin_percent=25.0,
                    quantity=1,
                    sale_date=datetime.utcnow() - timedelta(days=35),
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/sales/summary?days=30&months=6").json()

        assert body["total_sales"] == 0
        assert body["growth_revenue"] is None
        assert body["growth_profit"] is None
        assert "both the current and previous periods" in body[
            "growth_revenue_reason"
        ]


class TestMonthlyStats:
    def test_the_same_month_in_two_years_gets_two_rows(self, session_factory, client):
        client.post("/api/sales", json=_sale(sale_date="2025-10-15"))
        client.post("/api/sales", json=_sale(sale_date="2026-10-15"))

        from db.models import MonthlyStat

        session = session_factory()
        try:
            rows = (
                session.query(MonthlyStat)
                .order_by(MonthlyStat.year, MonthlyStat.month)
                .all()
            )
            assert [(row.year, row.month) for row in rows] == [
                (2025, 10),
                (2026, 10),
            ]
            assert all(row.total_sales == 1 for row in rows)
        finally:
            session.close()

    def test_update_moves_the_month_and_removes_the_old_row(self, session_factory, client):
        first = client.post(
            "/api/sales", json=_sale(sale_date="2026-09-10")
        ).json()
        client.put(
            f"/api/sales/{first['id']}",
            json=_sale(sale_date="2026-10-10", sale_price=50.0),
        )

        from db.models import MonthlyStat

        session = session_factory()
        try:
            rows = session.query(MonthlyStat).all()
            assert [(row.year, row.month) for row in rows] == [(2026, 10)]
            assert rows[0].total_revenue == 100.0
        finally:
            session.close()

    def test_delete_removes_the_now_empty_month(self, session_factory, client):
        created = client.post(
            "/api/sales", json=_sale(sale_date="2026-08-10")
        ).json()

        assert client.delete(f"/api/sales/{created['id']}").status_code == 200

        from db.models import MonthlyStat

        session = session_factory()
        try:
            assert session.query(MonthlyStat).count() == 0
        finally:
            session.close()

    def test_the_migration_replaces_separate_uniques_with_one_composite(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine, inspect, text

        import db.database as dbmod

        engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE monthly_stats ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "year INTEGER NOT NULL, "
                    "month INTEGER NOT NULL, "
                    "total_revenue FLOAT, "
                    "total_profit FLOAT, "
                    "total_sales INTEGER, "
                    "avg_margin FLOAT, "
                    "updated_at DATETIME, "
                    "UNIQUE (year), UNIQUE (month))"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO monthly_stats "
                    "(year, month, total_revenue, total_profit, total_sales, avg_margin) "
                    "VALUES (2025, 10, 10.0, 2.0, 1, 20.0), "
                    "(2026, 11, 20.0, 4.0, 1, 20.0)"
                )
            )

        monkeypatch.setattr(dbmod, "engine", engine)

        assert dbmod.ensure_monthly_stats_constraint() == "migrated"
        assert dbmod.ensure_monthly_stats_constraint() == "present"

        uniques = inspect(engine).get_unique_constraints("monthly_stats")
        assert [tuple(row["column_names"]) for row in uniques] == [("year", "month")]
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT year, month, total_revenue FROM monthly_stats ORDER BY year")
            ).fetchall()
            assert rows == [(2025, 10, 10.0), (2026, 11, 20.0)]

            # The repaired rule allows October in a second year, which the old
            # separate `UNIQUE (month)` made impossible.
            conn.execute(
                text(
                    "INSERT INTO monthly_stats "
                    "(year, month, total_revenue, total_profit, total_sales, avg_margin) "
                    "VALUES (2026, 10, 30.0, 6.0, 1, 20.0)"
                )
            )
            assert conn.execute(
                text("SELECT COUNT(*) FROM monthly_stats")
            ).scalar() == 3


class TestCsvImport:
    def test_export_shaped_headers_are_imported_and_recomputed(self, session_factory, client):
        csv_text = (
            "Date,Product,Category,Sale Price,Cost,Shipping,Fees,Profit,Margin %,Qty\n"
            "2026-10-01,Widget,Home,50,20,2,5,999,999,2\n"
        )

        resp = client.post(
            "/api/sales/import",
            json={"csv": csv_text, "filename": "sales.csv"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_declared"] is True
        assert body["rows_received"] == 1
        assert body["rows_imported"] == 1
        assert body["rows_rejected"] == 0
        assert len(body["imported_ids"]) == 1

        sales = client.get("/api/sales").json()["sales"]
        assert sales[0]["profit"] == 46.0
        assert sales[0]["margin_percent"] == 46.0

        from db.models import MonthlyStat

        session = session_factory()
        try:
            row = session.query(MonthlyStat).filter_by(year=2026, month=10).one()
            assert row.total_revenue == 100.0
            assert row.total_profit == 46.0
            assert row.total_sales == 1
        finally:
            session.close()

    def test_bad_rows_are_rejected_with_a_line_and_a_reason(self, client):
        csv_text = (
            "product_name,sale_price,supplier_cost,shipping_cost,ebay_fees,quantity,sale_date\n"
            "Good,10,3,1,1,1,2026-10-01\n"
            ",10,3,1,1,1,2026-10-02\n"
            "NoCost,10,,1,1,1,2026-10-03\n"
            "BadPrice,0,3,1,1,1,2026-10-04\n"
            "BadDate,10,3,1,1,1,not-a-date\n"
            "BadQty,10,3,1,1,0,2026-10-05\n"
        )

        body = client.post("/api/sales/import", json={"csv": csv_text}).json()

        assert body["rows_received"] == 6
        assert body["rows_imported"] == 1
        assert body["rows_rejected"] == 5
        assert [row["line"] for row in body["errors"]] == [3, 4, 5, 6, 7]
        assert "product_name" in body["errors"][0]["reason"]
        assert "supplier_cost" in body["errors"][1]["reason"]
        assert "greater than zero" in body["errors"][2]["reason"]
        assert "sale_date" in body["errors"][3]["reason"]
        assert "quantity" in body["errors"][4]["reason"]

    def test_missing_required_columns_are_refused(self, client):
        resp = client.post(
            "/api/sales/import",
            json={"csv": "product_name,sale_price\nWidget,10\n"},
        )

        assert resp.status_code == 422
        assert "missing required column" in resp.json()["detail"].lower()
        assert "supplier_cost" in resp.json()["detail"]

    def test_empty_csv_is_refused(self, client):
        resp = client.post("/api/sales/import", json={"csv": "   "})

        assert resp.status_code == 422
        assert "empty" in resp.json()["detail"].lower()


class TestThresholdReplay:
    def test_it_reports_only_rows_that_change_tier(self):
        from engine.thresholds import replay_thresholds

        rows = [
            {"match_score": 0.80, "verdict": "pass", "product_id": 1},
            {"match_score": 0.66, "verdict": "fail", "product_id": 2},
            {"match_score": 0.60, "verdict": "pending", "product_id": 3},
            {"match_score": 0.50, "verdict": None, "product_id": 4},
            {"match_score": None, "verdict": "pass", "product_id": 5},
        ]

        body = replay_thresholds(
            rows, proposed_verified=0.70, proposed_unverified=0.45
        )

        assert body["changes_applied"] is False
        assert body["current_tiers"] == {
            "verified": 2,
            "unverified": 2,
            "no_match": 0,
        }
        assert body["proposed_tiers"] == {
            "verified": 1,
            "unverified": 3,
            "no_match": 0,
        }
        assert body["sample"]["stored_rows"] == 5
        assert body["sample"]["scored_rows"] == 4
        assert body["sample"]["unscored_rows"] == 1
        assert body["differences"]["changed"] == 1
        assert body["differences"]["confirmed_lost"] == 1
        assert [row["change"] for row in body["differences"]["rows"]] == [
            "verified_to_unverified"
        ]
        assert body["outcomes"]["current_confirmed_by_verdict"]["pass"] == 1
        assert body["outcomes"]["proposed_confirmed_by_verdict"]["fail"] == 0
        assert body["sweep"]
        assert "never stored" in body["limitation"]
        assert "No threshold was changed" in body["note"]

    def test_a_lower_threshold_can_promote_stored_unconfirmed_rows(self):
        from engine.thresholds import replay_thresholds

        rows = [
            {"match_score": 0.66, "verdict": "pass", "product_id": 1},
            {"match_score": 0.60, "verdict": "pending", "product_id": 2},
        ]

        body = replay_thresholds(
            rows, proposed_verified=0.60, proposed_unverified=0.45
        )

        assert body["differences"]["confirmed_gained"] == 1
        assert [row["change"] for row in body["differences"]["rows"]] == [
            "unverified_to_verified"
        ]

    def test_the_route_reads_stored_scores_and_does_not_change_them(self, session_factory, client):
        from db.models import Product, SupplierMatch, Verdict

        session = session_factory()
        try:
            product = Product(
                ebay_url="https://www.ebay.co.uk/itm/1",
                title="Cordless Drill",
                price=100.0,
            )
            session.add(product)
            session.flush()
            session.add(Verdict(product_id=product.id, verdict="pass"))
            session.add_all(
                [
                    SupplierMatch(
                        product_id=product.id,
                        supplier_name="Supplier A",
                        supplier_title="Cordless Drill 18V",
                        match_score=0.80,
                    ),
                    SupplierMatch(
                        product_id=product.id,
                        supplier_name="Supplier B",
                        supplier_title="Cordless Drill 12V",
                        match_score=0.66,
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/sales/thresholds?verified=0.70").json()

        assert body["source"] == "stored_supplier_matches"
        assert body["sample"]["stored_rows"] == 2
        assert body["sample"]["scored_rows"] == 2
        assert body["differences"]["confirmed_lost"] == 1
        assert body["changes_applied"] is False
        assert body["current"]["verified"] == 0.65
        assert body["proposed"]["verified"] == 0.70

        # Reading the report never rewrites the scores.
        session = session_factory()
        try:
            scores = sorted(
                row.match_score
                for row in session.query(SupplierMatch).all()
            )
        finally:
            session.close()
        assert scores == [0.66, 0.8]

    def test_a_shown_threshold_above_the_confirmed_threshold_is_refused(self, client):
        resp = client.get("/api/sales/thresholds?verified=0.5&unverified=0.6")

        assert resp.status_code == 422
        assert "cannot be higher" in resp.json()["detail"]
