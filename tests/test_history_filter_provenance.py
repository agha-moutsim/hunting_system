"""A replayed run must carry the provenance the live run showed.

C13: the live screen labels every filter row — a rule nobody verified is
marked unverified, an advisory comparison is marked advisory. `save_verdict_data`
stored only name/passed/actual/expected, so History replayed those rows wearing
a PASS/FAIL badge they never earned.

The round trip is tested at the call site (`save_analysis_to_db`) because the
mapper is not the only failure point: a correct column still persists nothing
if the pipeline never puts the field in the dict.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import analysis_pipeline as ap
from db.database import Base
import db.models  # noqa: F401 - registers every table on Base.metadata
from engine.decisions import FilterResult, Verdict
from scrapers.base import ScrapedProduct


def _fresh_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'filters.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _results(filters):
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
        "verdict": Verdict(
            verdict="pending",
            filters=filters,
            profit=3.2,
            margin=25.6,
            profit_computed=True,
            scorecard="pending - one rule unverified",
        ),
    }


def _stored_filter_results(factory):
    from db.models import Verdict as VerdictRow

    session = factory()
    try:
        row = session.query(VerdictRow).one()
        return row.filter_results
    finally:
        session.close()


@pytest.fixture()
def store(tmp_path, monkeypatch):
    factory = _fresh_session_factory(tmp_path)
    monkeypatch.setattr(ap, "SessionLocal", factory)
    return factory


class TestFilterProvenanceSurvivesTheSave:
    def test_an_unverified_rule_is_stored_as_unverified(self, store):
        ap.save_analysis_to_db(_results([
            FilterResult(
                name="Demand (7d)",
                passed=False,
                actual="0 sold",
                expected="≥1 sold",
                verified=False,
            ),
        ]))

        row = _stored_filter_results(store)[0]
        assert row["verified"] is False
        assert row["advisory"] is False

    def test_an_advisory_row_keeps_its_mark(self, store):
        ap.save_analysis_to_db(_results([
            FilterResult(
                name="Delivery (advisory)",
                passed=True,
                actual="5 days",
                expected="3–8 days",
                verified=True,
                advisory=True,
            ),
        ]))

        row = _stored_filter_results(store)[0]
        assert row["verified"] is True
        assert row["advisory"] is True

    def test_the_columns_are_stored_as_booleans_not_strings(self, store):
        """A string "false" is truthy in the UI: the mark has to be a boolean."""
        ap.save_analysis_to_db(_results([
            FilterResult(
                name="Condition",
                passed=True,
                actual="New",
                expected="New",
                verified=False,
            ),
        ]))

        row = _stored_filter_results(store)[0]
        assert row["verified"] is False
        assert isinstance(row["verified"], bool)
        assert isinstance(row["advisory"], bool)

    def test_the_original_fields_are_untouched(self, store):
        ap.save_analysis_to_db(_results([
            FilterResult(
                name="Profit margin",
                passed=True,
                actual="25.6%",
                expected="≥25%",
                verified=True,
            ),
        ]))

        row = _stored_filter_results(store)[0]
        assert row["name"] == "Profit margin"
        assert row["passed"] is True
        assert row["actual"] == "25.6%"
        assert row["expected"] == "≥25%"
