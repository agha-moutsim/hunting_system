"""P5 browser-extension bridge — parser, capture endpoint, pipeline override.

No network anywhere: the parser reads synthetic HTML (★ fixture shape is an
assumption — see backend/utils/purchase_history.py), the endpoint runs against
a throwaway SQLite database, and the pipeline override is exercised through
the apply_purchase_history seam with an injected session.
"""

import json
from datetime import date, datetime, timedelta

import pytest

from engine.decisions import DecisionEngine
from scrapers.base import DemandData, ScrapedProduct
from utils.purchase_history import extract_item_id, parse_purchase_history

# Fixed clock — every window assertion below is relative to this.
NOW = datetime(2026, 9, 20, 12, 0, 0)


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Same fixture as test_verdict_engine — DecisionEngine sees default bands."""
    import utils.filters as uf
    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


def _days(n: int):
    """A date n days before NOW."""
    return (NOW - timedelta(days=n)).date()


def _table_html(rows):
    """★ SYNTHETIC fixture markup (table shape is an assumption to verify).

    rows: iterable of (date_text, price_text, title); falsy date/price
    renders an empty cell.
    """
    body = "".join(
        "<tr>"
        f"<td class='ph-title'>{title}</td>"
        f"<td class='ph-date'>{date_text or ''}</td>"
        f"<td class='ph-price'>{price_text or ''}</td>"
        "</tr>"
        for date_text, price_text, title in rows
    )
    return (
        "<html><body><div class='purchase-history'>"
        "<table class='ph-table'>"
        "<thead><tr><th>Item</th><th>Date of purchase</th><th>Price</th></tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table></div></body></html>"
    )


def _product():
    return ScrapedProduct(
        source="ebay_uk",
        title="Generic widget",
        price=12.0,
        url="https://www.ebay.co.uk/itm/1",
        condition="New",
        delivery_days_max=5,
        verified=True,
    )


def _filter(verdict, name):
    return next(f for f in verdict.filters if f.name == name)


# ── parser (pure, no network) ────────────────────────────────────────────

class TestParsePurchaseHistory:
    def test_counts_7d_and_30d_when_the_window_is_covered(self):
        html = _table_html([
            (f"{_days(3):%d/%m/%Y}", "£12.99", "A"),     # UK numeric date
            (f"{_days(5):%d} Sep 2026", "20.00", "B"),    # UK text date
            (f"{_days(10):%Y-%m-%d}", "£8.50", "C"),      # ISO date
            (f"{_days(25):%d} Aug 2026", "£15.50", "D"),  # oldest in window
            (f"{_days(40):%d/%m/%Y}", "£9.99", "E"),      # proves 30d coverage
        ])
        res = parse_purchase_history(html, now=NOW)

        assert res["rows_seen"] == 5
        assert len(res["sales"]) == 5
        assert res["sales"][0] == {"date": _days(3).isoformat(), "price": 12.99}
        assert res["sold_7d"] == 2       # days 3 and 5
        assert res["sold_30d"] == 4      # everything except the 40-day-old sale

    def test_rows_missing_date_or_price_are_counted_but_never_guessed(self):
        html = _table_html([
            ("", "£12.99", "no date"),
            (f"{_days(2):%Y-%m-%d}", "", "no price"),
            (f"{_days(2):%d/%m/%Y}", "£4.99", "good row"),
        ])
        res = parse_purchase_history(html, now=NOW)

        assert res["rows_seen"] == 3
        assert len(res["sales"]) == 1
        assert res["sold_7d"] == 1
        assert res["sold_30d"] is None   # one recent row proves no coverage

    def test_unrecognised_page_is_all_none_and_empty(self):
        empty = {"sales": [], "sold_7d": None, "sold_30d": None, "rows_seen": 0}
        assert parse_purchase_history(
            "<html><body><p>Sign in to continue</p></body></html>", now=NOW
        ) == empty
        assert parse_purchase_history("", now=NOW) == empty

    def test_rows_exist_but_none_is_parseable_means_not_stored(self):
        html = _table_html([("yesterday", "cheap", "junk"), ("", "", "junk")])
        res = parse_purchase_history(html, now=NOW)
        assert res["rows_seen"] == 2
        assert res["sales"] == []
        assert res["sold_7d"] is None
        assert res["sold_30d"] is None

    def test_sold_30d_is_none_when_the_capture_does_not_cover_30_days(self):
        html = _table_html([
            (f"{_days(2):%d/%m/%Y}", "£12.99", "A"),
            (f"{_days(20):%d/%m/%Y}", "£9.99", "B"),  # oldest row is 20 days old
        ])
        res = parse_purchase_history(html, now=NOW)
        assert res["rows_seen"] == 2
        assert res["sold_7d"] == 1
        assert res["sold_30d"] is None

    def test_zero_sales_in_window_is_zero_not_none(self):
        html = _table_html([
            (f"{_days(10):%d/%m/%Y}", "£12.99", "A"),
            (f"{_days(12):%d/%m/%Y}", "£11.99", "B"),
            (f"{_days(40):%d/%m/%Y}", "£9.99", "C"),   # covers the 30-day window
        ])
        res = parse_purchase_history(html, now=NOW)
        assert res["sold_7d"] == 0
        assert res["sold_7d"] is not None
        assert res["sold_30d"] == 2

    def test_future_dated_rows_are_kept_but_never_counted(self):
        # Live-smoke caught a clock-skew row inflating the verified count (C1).
        html = _table_html([
            (f"{_days(-2):%d/%m/%Y}", "£12.99", "future row"),
            (f"{_days(2):%d/%m/%Y}", "£9.99", "recent row"),
            (f"{_days(40):%d/%m/%Y}", "£8.99", "coverage row"),
        ])
        res = parse_purchase_history(html, now=NOW)
        assert res["rows_seen"] == 3
        assert len(res["sales"]) == 3   # kept for transparency
        assert res["sold_7d"] == 1      # only the real row counts
        assert res["sold_30d"] == 1     # recent row only; future + 40d-old excluded

    def test_list_style_markup_is_parsed_when_there_is_no_table(self):
        html = (
            "<ul class='order-history'>"
            "<li class='order-row'><span>Vintage lamp</span>"
            "<span>17 Sep 2026</span><span>£24.99</span></li>"
            "<li class='order-row'><span>Mug set</span>"
            "<span>01 Sep 2026</span><span>£7.50</span></li>"
            "</ul>"
        )
        res = parse_purchase_history(html, now=NOW)
        assert res["rows_seen"] == 2
        assert res["sold_7d"] == 1
        assert res["sold_30d"] is None
        assert {s["price"] for s in res["sales"]} == {24.99, 7.50}


class TestParseDate:
    @pytest.mark.parametrize("text,expected", [
        ("12 Sep 2026", date(2026, 9, 12)),
        ("12 September 2026", date(2026, 9, 12)),
        ("12/09/2026", date(2026, 9, 12)),      # UK day-first
        ("13/09/2026", date(2026, 9, 13)),      # unambiguous day-first
        ("09/13/2026", date(2026, 9, 13)),      # unambiguous month-first
        ("2026-09-12", date(2026, 9, 12)),      # ISO
        ("2026-09-12T10:03:00", date(2026, 9, 12)),
        ("Sep 12, 2026", date(2026, 9, 12)),
        ("31/02/2026", None),                   # impossible date
        ("yesterday", None),
        ("", None),
    ])
    def test_common_uk_formats(self, text, expected):
        from utils.purchase_history import parse_date
        assert parse_date(text) == expected


class TestExtractItemId:
    @pytest.mark.parametrize("url,expected", [
        ("https://www.ebay.co.uk/itm/1234567890", "1234567890"),
        ("https://www.ebay.co.uk/itm/great-widget/1234567890?ul_redir=true", "1234567890"),
        ("https://www.ebay.co.uk/bin/purchaseHistory?item=555666777", "555666777"),
        ("https://www.ebay.co.uk/sch/i.html?_nkw=widget", None),
        ("", None),
        (None, None),
    ])
    def test_item_id_extraction(self, url, expected):
        assert extract_item_id(url) == expected


# ── shared fixtures: throwaway DB + client ───────────────────────────────

def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    import db.models  # noqa: F401 — registers every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'bridge.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def bridge_sessions(tmp_path):
    return _fresh_session_factory(tmp_path)


@pytest.fixture()
def ext_client(bridge_sessions, monkeypatch):
    # api.extension imports SessionLocal lazily (repo convention), so the
    # seam is the db.database module attribute itself.
    monkeypatch.setattr("db.database.SessionLocal", bridge_sessions)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        yield client


def _payload(item_id, *, days_ago=2, price="£12.99", url=None):
    row = (f"{_days(days_ago):%d/%m/%Y}", price, "Generic widget")
    return {
        "item_id": item_id,
        "url": url or f"https://www.ebay.co.uk/itm/{item_id}",
        "html": _table_html([row]),
        # Fixed capture time so the 7-day window is deterministic (the
        # parser counts relative to captured_at, not the server clock).
        "captured_at": NOW.isoformat(),
    }


# ── capture endpoint ─────────────────────────────────────────────────────

class TestSoldHistoryEndpoint:
    def test_valid_capture_is_stored_and_readable(self, ext_client):
        resp = ext_client.post("/api/extension/sold-history", json=_payload("888000111"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["stored"] is True
        assert body["item_id"] == "888000111"
        assert body["sold_7d"] == 1
        assert body["sold_30d"] is None
        assert body["captured_at"]

        got = ext_client.get("/api/extension/sold-history/888000111")
        assert got.status_code == 200
        data = got.json()
        assert data["item_id"] == "888000111"
        assert data["sold_7d"] == 1
        assert len(data["sales"]) == 1
        assert data["sales"][0]["price"] == 12.99
        assert data["source"] == "extension"

    def test_unparseable_html_is_not_stored(self, ext_client):
        resp = ext_client.post("/api/extension/sold-history", json={
            "item_id": "777000111",
            "url": "https://www.ebay.co.uk/itm/777000111",
            "html": "<html><body><p>Sign in to continue</p></body></html>",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["stored"] is False
        assert body["reason"]
        # Nothing was persisted.
        assert ext_client.get("/api/extension/sold-history/777000111").status_code == 404

    def test_rows_without_parseable_date_or_price_are_not_stored(self, ext_client):
        html = _table_html([("yesterday", "cheap", "junk")])
        resp = ext_client.post(
            "/api/extension/sold-history", json={"item_id": "777000222", "html": html}
        )
        assert resp.status_code == 200
        assert resp.json()["stored"] is False
        assert "candidate row" in resp.json()["reason"]
        assert ext_client.get("/api/extension/sold-history/777000222").status_code == 404

    def test_second_capture_replaces_the_first(self, ext_client, bridge_sessions):
        first = ext_client.post("/api/extension/sold-history", json=_payload("555000111"))
        assert first.json()["sold_7d"] == 1

        # A later capture with two in-window sales.
        later = _payload("555000111", days_ago=1, price="£10.00")
        later["html"] = _table_html([
            (f"{_days(1):%d/%m/%Y}", "£10.00", "A"),
            (f"{_days(6):%d/%m/%Y}", "£10.00", "B"),
        ])
        second = ext_client.post("/api/extension/sold-history", json=later)
        assert second.json()["stored"] is True
        assert second.json()["sold_7d"] == 2

        got = ext_client.get("/api/extension/sold-history/555000111")
        assert got.json()["sold_7d"] == 2
        assert len(got.json()["sales"]) == 2

        # Latest wins, and there is exactly one row per item_id.
        db = bridge_sessions()
        try:
            from db.models import PurchaseCapture
            rows = db.query(PurchaseCapture).filter_by(item_id="555000111").all()
            assert len(rows) == 1
            assert rows[0].sold_7d == 2
        finally:
            db.close()

    def test_missing_capture_is_404_with_error_shape(self, ext_client):
        resp = ext_client.get("/api/extension/sold-history/000000000")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_captured_at_is_honoured_and_normalised_to_utc(self, ext_client):
        payload = _payload("666000111")
        payload["captured_at"] = "2026-09-20T10:30:00+00:00"
        body = ext_client.post("/api/extension/sold-history", json=payload).json()
        assert body["captured_at"] == "2026-09-20T10:30:00"


# ── pipeline override (the TDD seam: apply_purchase_history) ─────────────

@pytest.fixture()
def capture_factory(bridge_sessions):
    from db.models import PurchaseCapture

    def _create(item_id, *, sold_7d=9, sold_30d=40, captured_at=None):
        db = bridge_sessions()
        try:
            row = PurchaseCapture(
                item_id=str(item_id),
                url=f"https://www.ebay.co.uk/itm/{item_id}",
                sold_7d=sold_7d,
                sold_30d=sold_30d,
                sales_json=json.dumps([{"date": "2026-09-18", "price": 12.99}]),
                captured_at=captured_at or datetime.utcnow(),
                source="extension",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        finally:
            db.close()

    return _create


class TestPipelineOverride:
    def test_fresh_capture_marks_the_7d_evidence_verified(self, bridge_sessions, capture_factory):
        capture_factory("1234567890", sold_7d=9)
        demand = DemandData(sold_count_30d=40, sold_count_7d=None, verified=False)

        from analysis_pipeline import apply_purchase_history
        out = apply_purchase_history(
            demand,
            "https://www.ebay.co.uk/itm/great-widget/1234567890?ul_redir=true",
            db=bridge_sessions(),
        )

        assert out.sold_count_7d == 9
        assert out.verified_7d is True
        assert out.data_source.endswith("+purchase_history")
        # 30-day side is untouched.
        assert out.sold_count_30d == 40
        assert out.verified is False

        v = DecisionEngine().evaluate(_product(), out, 6.0)
        row7 = _filter(v, "Demand (7d)")
        assert row7.verified is True
        assert row7.passed is True            # 9 >= 8
        assert _filter(v, "Demand (30d)").verified is False  # keeps its source

    def test_capture_older_than_24h_is_ignored(self, bridge_sessions, capture_factory):
        capture_factory(
            "1234567890", sold_7d=9,
            captured_at=datetime.utcnow() - timedelta(hours=25),
        )
        demand = DemandData(sold_count_30d=40, sold_count_7d=None, verified=False)

        from analysis_pipeline import apply_purchase_history
        out = apply_purchase_history(
            demand, "https://www.ebay.co.uk/itm/1234567890", db=bridge_sessions()
        )

        assert out.sold_count_7d is None
        assert out.verified_7d is None
        assert out.data_source is None
        v = DecisionEngine().evaluate(_product(), out, 6.0)
        # Nothing parseable for 7d -> the row is unverified, verdict pending.
        assert _filter(v, "Demand (7d)").verified is False
        assert v.verdict == "pending"

    def test_missing_capture_or_unusable_url_leaves_demand_untouched(self, bridge_sessions):
        from analysis_pipeline import apply_purchase_history

        demand = DemandData(sold_count_30d=40, sold_count_7d=None, verified=False)
        out = apply_purchase_history(
            demand, "https://www.ebay.co.uk/sch/i.html?_nkw=widget", db=bridge_sessions()
        )
        assert out.sold_count_7d is None
        assert out.verified_7d is None
        assert out.data_source is None

        # Item id present but no capture row stored for it.
        out2 = apply_purchase_history(
            DemandData(verified=False),
            "https://www.ebay.co.uk/itm/999888777",
            db=bridge_sessions(),
        )
        assert out2.verified_7d is None

    def test_engine_falls_back_to_demand_verified_when_verified_7d_is_absent(self):
        # Default DemandData has verified_7d=None — behaviour must not change.
        demand = DemandData(sold_count_30d=40, sold_count_7d=10, verified=False)
        assert demand.verified_7d is None
        v = DecisionEngine().evaluate(_product(), demand, 6.0)
        assert _filter(v, "Demand (7d)").verified is False
        assert _filter(v, "Demand (30d)").verified is False

    def test_saved_demand_row_records_the_purchase_history_source(self, bridge_sessions):
        from db.queries import save_demand_data, save_product

        db = bridge_sessions()
        try:
            product_id = save_product(db, _product())
            demand = DemandData(
                sold_count_30d=40,
                sold_count_7d=9,
                verified=False,
                verified_7d=True,
                data_source="ebay_sold_listings+purchase_history",
            )
            row = save_demand_data(db, product_id, demand)
            assert row.sold_count_7d == 9
            assert row.data_source == "ebay_sold_listings+purchase_history"
            assert row.verified is False   # original source's status is kept
        finally:
            db.close()
