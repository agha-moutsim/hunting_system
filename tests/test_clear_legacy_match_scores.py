"""The legacy-score cleanup must only ever touch the legacy pair.

`save_analysis_to_db` used to write three hard-coded constants as if they
were measurements - supplier_type "dropship", confidence "medium", match_score
0.5. So every row saved before the C14 matcher was wired carries a 0.5 no
matcher produced.

The cleanup selects on `match_score = 0.5 AND confidence = 'medium'`, and
this file exists to prove that selection cannot reach anything else. The
danger case is a genuine future row whose real score happens to be exactly
0.5: it must survive, because it is a measurement and 0.5 is a legitimate
score in a 0..1 range.

These tests write temporary rows to the live table and remove them, so the
predicate under test is the real SQL rather than a Python re-implementation
of it that could drift.
"""

import pytest

from db.database import SessionLocal
from db.models import SupplierMatch
from scripts.clear_legacy_match_scores import (
    LEGACY_CONFIDENCE,
    LEGACY_SCORE,
    find_legacy,
)


@pytest.fixture
def db():
    session = SessionLocal()
    created: list[int] = []
    yield session, created
    for row_id in created:
        session.query(SupplierMatch).filter(SupplierMatch.id == row_id).delete()
    session.commit()
    session.close()


def _make(db, created, score, confidence):
    row = SupplierMatch(
        supplier_name="TESTONLY",
        supplier_url="https://example.invalid/p",
        supplier_title="temporary row",
        supplier_price=1.0,
        match_score=score,
        confidence=confidence,
    )
    db.add(row)
    db.commit()
    created.append(row.id)
    return row


class TestOnlyTheLegacyPairIsSelected:
    def test_the_legacy_pair_is_found(self, db):
        session, created = db
        _make(session, created, LEGACY_SCORE, LEGACY_CONFIDENCE)

        assert len(find_legacy(session)) == 1

    def test_a_genuine_score_of_zero_point_five_survives(self, db):
        """The case that matters: 0.5 is a legal score in a 0..1 range, so a
        real row carrying one must not be mistaken for the legacy constant.
        Post-2026-10-03 rows are stamped 'high' or 'low', never 'medium'."""
        session, created = db
        row = _make(session, created, LEGACY_SCORE, "high")

        found = [r.id for r in find_legacy(session)]
        assert row.id not in found

    def test_a_low_confidence_row_survives(self, db):
        session, created = db
        row = _make(session, created, LEGACY_SCORE, "low")

        assert row.id not in [r.id for r in find_legacy(session)]

    def test_a_null_score_row_survives(self, db):
        session, created = db
        row = _make(session, created, None, None)

        assert row.id not in [r.id for r in find_legacy(session)]

    def test_either_half_alone_is_not_enough(self, db):
        """Only the pair is legacy. A score of 0.5 with some other confidence,
        or 'medium' with a real score, is not the constant pair."""
        session, created = db
        a = _make(session, created, LEGACY_SCORE, None)
        b = _make(session, created, 0.77, LEGACY_CONFIDENCE)

        found = [r.id for r in find_legacy(session)]
        assert a.id not in found
        assert b.id not in found

    def test_the_cleanup_is_idempotent(self, db):
        """Running it twice must not keep finding rows, or worse, start
        matching something new."""
        session, created = db
        _make(session, created, LEGACY_SCORE, LEGACY_CONFIDENCE)

        assert len(find_legacy(session)) == 1
        for row in find_legacy(session):
            row.match_score = None
            row.confidence = None
        session.commit()

        assert find_legacy(session) == []


class TestTheRealTableIsClean:
    def test_no_legacy_rows_remain_in_the_live_table(self):
        """The user's own data. If this fails, the cleanup was never run."""
        session = SessionLocal()
        try:
            assert find_legacy(session) == []
        finally:
            session.close()