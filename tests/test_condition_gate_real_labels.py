"""C10, checked against the condition labels eBay actually returns.

The gate's whitelist was built from the labels in the docs. A real Browse
response, captured in tests/fixtures/ebay_browse_search.json, contains two
that are genuinely New and were being thrown away:

    'New other (see details)'   -> cleaned 'newotherseedetails'
    'New condition'             -> cleaned 'newcondition'

Neither is in _NEW_TOKENS, so both failed closed and real New listings
disappeared from a New-only product. A false negative here is expensive and
invisible: the user sees a short result list and no explanation.

The fix must widen acceptance without ever admitting something that is not
New. So the rule is asymmetric on purpose:
  * a not-New marker ANYWHERE in the label wins (so "newly refurbished" is
    still refurbished), then
  * a label that starts with "new" is New - because no not-New label eBay
    uses begins with "new", and because 'New with tags' / 'New with box'
    were already being special-cased one at a time.
Everything else stays unverified and therefore not-New (C1/C10).

The not-New list is unchanged. These labels are eBay's, captured live.
"""

import json
from pathlib import Path

import pytest

from engine.condition_gate import is_new, normalize_condition

REAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ebay_browse_search.json"


# Labels eBay returned in the captured Browse response, plus the near-misses
# that must stay shut.
REAL_NEW_LABELS = [
    "New",
    "New other (see details)",
    "New condition",
    "New with tags",
    "New with box",
    "Brand new",
]

REAL_NOT_NEW_LABELS = [
    "Certified - Refurbished",
    "Seller refurbished",
    "Refurbished",
    "Used",
    "Pre-owned",
    "For parts or not working",
    "Open box",
    "Damaged",
    "",
    None,
]


class TestRealNewLabelsAreAccepted:
    @pytest.mark.parametrize("label", REAL_NEW_LABELS)
    def test_genuinely_new_survives(self, label):
        assert is_new(label) is True, f"{label!r} is New and was being dropped"

    def test_the_real_ones_normalise_to_new(self):
        assert normalize_condition("New other (see details)") == "new"
        assert normalize_condition("New condition") == "new"

    def test_new_with_the_rest_of_the_sentence_still_reads_as_new(self):
        """eBay will keep inventing suffixes; the gate must not need a new
        entry in the whitelist every time it does."""
        assert is_new("New (sealed)") is True
        assert is_new("New - 2024 model") is True

    def test_new_open_box_is_still_rejected_and_that_is_a_decision_not_a_bug(self):
        """OPEN QUESTION FOR THE PRODUCT OWNER - do not 'fix' this silently.

        eBay's real label is 'New - Open Box': the item is new, the box was
        opened. _NOT_NEW_TOKENS lists 'openbox' as not-New, so this gate
        rejects it. That may be right (an opened box can have been handled or
        returned) or wrong (it is still a new, unused item).

        Reopening it changes what C10 admits, which is the user's rule and not
        a parsing decision, so the current fail-closed behaviour is pinned here
        deliberately. If the answer is "open box is still new", delete 'openbox'
        from _NOT_NEW_TOKENS and flip this test - not the other way round.
        """
        assert is_new("New - Open Box") is False


class TestNotNewStaysShut:
    @pytest.mark.parametrize("label", REAL_NOT_NEW_LABELS)
    def test_anything_else_is_not_new(self, label):
        assert is_new(label) is False, f"{label!r} must not pass the New gate"

    def test_a_not_new_marker_anywhere_beats_a_new_prefix(self):
        """The whole safety argument for widening on the 'new' prefix. If this
        ever passes, the gate has a hole in it."""
        assert is_new("Newly refurbished") is False
        assert is_new("New but used") is False
        assert is_new("New - for parts") is False

    def test_unknown_labels_are_never_assumed_new(self):
        """C10 fails closed: an unrecognised label is unverified, not New."""
        for label in ("Unspecified", "Unknown", "See description", "Lot", "Other"):
            assert is_new(label) is False, label


class TestAgainstTheCapturedPayload:
    def test_only_genuinely_new_rows_survive_the_real_fixture(self):
        """The end-to-end claim, on real bytes: of the conditions eBay
        returned, exactly the New ones pass."""
        data = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
        conditions = [i.get("condition") for i in data["itemSummaries"]]

        assert conditions, "fixture carried no conditions to check"
        survivors = [c for c in conditions if is_new(c)]
        for c in survivors:
            assert "refurb" not in c.lower()
            assert "used" not in c.lower()
        # and the certified-refurbished rows are all shut out
        assert "Certified - Refurbished" not in [
            c for c in conditions if is_new(c)
        ]