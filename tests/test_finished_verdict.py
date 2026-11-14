"""C1 — a finished run that measured nothing has no verdict to store.

`DecisionEngine` answers ``pending`` both when the money was measured and
only the 7-day demand lacks a capture, and when nothing was priced at all.
The second is not a decision held for evidence: the Analyze run is over, no
later step will supply a supplier price, and a stored ``pending`` would
promise a verdict that is never coming. The live payload and the stored row
both carry an absent verdict, which every surface renders NOT RECORDED.

The money-backed ``pending`` is deliberately untouched: that decision is
genuinely waiting for a purchase-history capture, and a real ``fail`` stays a
fail even when no profit was computed.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import analysis_pipeline as ap
from db.database import Base
import db.models  # noqa: F401 - registers every table on Base.metadata
from engine.decisions import Verdict, resolved_verdict
from scrapers.base import ScrapedProduct


def _verdict(status="pending", *, computed, profit=0.0, margin=0.0):
    return Verdict(
        verdict=status,
        profit=profit,
        margin=margin,
        profit_computed=computed,
    )


class TestResolvedVerdict:
    def test_an_unpriced_pending_becomes_absent(self):
        assert resolved_verdict(_verdict(computed=False)).verdict == ""

    def test_a_pending_with_measured_money_is_kept(self):
        v = _verdict(computed=True, profit=3.2, margin=25.6)
        assert resolved_verdict(v).verdict == "pending"
        assert v.profit == 3.2

    def test_a_verified_failure_survives_without_profit(self):
        # The engine can know a rule is broken even when no supplier price
        # arrived; that is a real decision, not an absent one.
        assert resolved_verdict(_verdict("fail", computed=False)).verdict == "fail"

    def test_a_pass_is_untouched(self):
        assert resolved_verdict(_verdict("pass", computed=True)).verdict == "pass"


def _results(verdict):
    return {
        "ebay_product": ScrapedProduct(
            source="ebay_uk",
            title="Stainless Steel Water Bottle",
            price=12.5,
            url="https://www.ebay.co.uk/itm/2001",
            condition="New",
            verified=True,
        ),
        "demand": None,
        "supplier_matches": [],
        "llm_analysis": None,
        "verdict": verdict,
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'verdict.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ap, "SessionLocal", factory)
    return factory


def _stored_verdict(factory):
    from db.models import Verdict as VerdictRow

    session = factory()
    try:
        return session.query(VerdictRow).one().verdict
    finally:
        session.close()


class TestTheStoragePathFollowsTheRule:
    def test_an_unpriced_pending_is_stored_as_no_verdict(self, store):
        ap.save_analysis_to_db(_results(_verdict(computed=False)))

        assert _stored_verdict(store) == ""

    def test_a_pending_with_measured_money_is_stored_as_pending(self, store):
        ap.save_analysis_to_db(
            _results(_verdict(computed=True, profit=3.2, margin=25.6))
        )

        assert _stored_verdict(store) == "pending"

    def test_a_fail_with_no_profit_is_still_stored_as_fail(self, store):
        ap.save_analysis_to_db(_results(_verdict("fail", computed=False)))

        assert _stored_verdict(store) == "fail"
