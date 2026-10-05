"""The matcher's score must survive the journey to the database.

`analysis_pipeline._score_supplier` runs the C14 matcher and writes
`match_score` and `match_tier` onto each supplier row - that score is what
decides verified vs unverified, and what Hunter sorts on. Then
`save_analysis_to_db` persisted `"match_score": None` with a comment saying no
matcher had run yet. One did. P4 wired the matcher after that comment was
written, and the audit trail was never updated to match.

The cost is real and quiet: the verdict is correct on screen, but asking the
database "why was this supplier rejected?" returns nothing. That breaks the
project's own promise - every number traceable, or explicitly unverified.

Two rules, and the second is the one that matters:
  1. a computed score is persisted as itself;
  2. an UNSCORED row is persisted as NULL, not as 0.0. A 0.0 in a 0..1 score
     column is indistinguishable from a real zero score, which is the exact
     "unknown value shown as a known one" failure C1 forbids.
"""

import pytest

from scrapers.base import ScrapedProduct

pytestmark = pytest.mark.usefixtures("_no_live_db")


@pytest.fixture
def _no_live_db(monkeypatch):
    """Capture what save_analysis_to_db hands to the persistence layer,
    without writing to the real database."""
    import analysis_pipeline as ap

    saved: list[dict] = []
    monkeypatch.setattr(ap, "save_supplier_match_data",
                        lambda db, product_id, data: saved.append(data))
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


def _supplier(score=None, tier=""):
    s = ScrapedProduct(
        source="Toolstation", title="6ft Greenhouse", price=45.0,
        url="https://www.toolstation.com/p/1", condition="", verified=True,
    )
    s.match_score = score if score is not None else 0.0
    s.match_tier = tier
    return s


class TestComputedScoreIsPersisted:
    def test_the_real_score_reaches_the_database(self, _no_live_db):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=0.82, tier="verified")))

        assert _no_live_db[0]["match_score"] == pytest.approx(0.82)

    def test_a_verified_tier_is_recorded_as_high_confidence(self, _no_live_db):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=0.82, tier="verified")))

        assert _no_live_db[0]["confidence"] == "high"

    def test_an_unverified_tier_is_recorded_as_low_confidence(self, _no_live_db):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=0.41, tier="unverified")))

        assert _no_live_db[0]["confidence"] == "low"
        assert _no_live_db[0]["match_score"] == pytest.approx(0.41)


class TestAnUnscoredRowIsNeverGivenAZeroScore:
    def test_an_unscored_row_persists_null_not_zero(self, _no_live_db):
        """The distinction the whole file exists for: 0.0 is a real score,
        None is 'we never scored it'. Writing 0.0 for the second invents a
        measurement."""
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=None, tier="")))

        assert _no_live_db[0]["match_score"] is None

    def test_an_unscored_row_has_no_confidence(self, _no_live_db):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=None, tier="")))

        assert _no_live_db[0]["confidence"] is None

    def test_an_unrecognised_tier_is_not_guessed_into_a_confidence(self, _no_live_db):
        """A tier this code has never heard of must stay unknown."""
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=0.7, tier="brand_new_tier")))

        assert _no_live_db[0]["confidence"] is None

    def test_a_real_zero_score_is_still_kept(self, _no_live_db):
        """0.0 with a real tier is a genuine 'nothing matched' and must be
        stored - the fix must not throw away the one true zero."""
        import analysis_pipeline as ap

        ap.save_analysis_to_db(_results(_supplier(score=0.0, tier="no_match")))

        assert _no_live_db[0]["match_score"] == 0.0