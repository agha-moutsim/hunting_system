r"""C13 — Analyze supplier rows must carry a provenance label.

ScrapedProduct carried only `verified: bool` and no label at all. The
frontend draws a badge only when `provenance` is present (or `verified` is
false), so every Analyze supplier row rendered with NO provenance badge —
including rows read straight off the eBay Browse API or a parsed supplier
page. C13 says every factual value carries one of the four labels and that
the label is DATA, not a UI decision, so it is derived on the backend.

`stamp_scraped_product` is the derivation: `verified` decides the tier, an
explicit stamp from the scraper that actually read the row always wins, and
an unstamped row stays empty until something stamps it — a row that has read
nothing must not claim it did.
"""

import pytest

import analysis_pipeline as ap
from engine.provenance import Provenance, stamp_scraped_product
from scrapers.base import ScrapedProduct

from tests.test_store_wiring import (
    _FakeAnalyzer,
    _Stub,
    _demand,
    _ebay_product,
    _sold_data,
)

# Must match the stubbed eBay listing's title (see _ebay_product), or the
# C14 matcher drops the row before it can ever be stamped — correctly.
EBAY_TITLE = "Generic widget"


def _row(**kw) -> ScrapedProduct:
    return ScrapedProduct(
        source="aliexpress", title=EBAY_TITLE, price=9.99,
        url="https://www.aliexpress.com/item/1.html",
        condition="New", **kw,
    )


class TestTheDerivation:
    def test_a_row_that_was_read_becomes_verified(self):
        out = stamp_scraped_product(_row())

        assert out.provenance == Provenance.VERIFIED.value
        assert out.provenance_label == "Verified"

    def test_a_row_that_was_not_read_becomes_unverified(self):
        out = stamp_scraped_product(_row(verified=False))

        assert out.provenance == Provenance.UNVERIFIED.value
        assert out.provenance_label == "Unverified"

    def test_an_explicit_stamp_from_the_scraper_wins(self):
        """The scraper that read the row knows more than this derivation
        does; it must never be silently rewritten."""
        row = _row(provenance="estimated", provenance_label="Estimated")

        stamp_scraped_product(row)

        assert row.provenance == "estimated"
        assert row.provenance_label == "Estimated"

    def test_an_empty_stamp_is_still_a_stamp_so_it_is_not_overwritten(self):
        """Distinguishing '' from unset is what keeps this from clobbering a
        deliberately blank label."""
        row = _row(provenance="", provenance_label="")
        stamp_scraped_product(row)
        assert row.provenance == Provenance.VERIFIED.value

    def test_none_passes_through(self):
        assert stamp_scraped_product(None) is None

    def test_an_unstamped_row_says_nothing_at_all(self):
        """Before stamping: no claim. The badge must not appear for free."""
        assert _row().provenance == ""
        assert _row().provenance_label == ""


class TestTheAnalyzePathStampsItsRows:
    """The wiring that actually reaches the /api/analyze response."""

    @pytest.fixture()
    def run_with(self, monkeypatch):
        from scrapers.ebay import EbayScraper
        from scrapers.ebay_sold import EbaySoldScraper

        def _run(suppliers):
            async def _search(query, progress=None):
                return list(suppliers)

            # Every collaborator that could reach the network, replaced.
            monkeypatch.setattr(ap, "apply_purchase_history",
                                lambda demand, url, db=None: demand)
            monkeypatch.setattr(ap, "search_all_suppliers", _search)
            monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
            monkeypatch.setattr(ap, "resolve_stores",
                                lambda *a, **k: [])
            monkeypatch.setattr(EbayScraper, "search",
                                _Stub(result=[_ebay_product()]))
            monkeypatch.setattr(EbayScraper, "get_details",
                                _Stub(result=_ebay_product()))
            monkeypatch.setattr(EbayScraper, "get_sold_data",
                                _Stub(result=_demand([])))
            monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                                _Stub(result=_sold_data(top=False)))

            return ap.run_async(ap.run_analysis_pipeline("generic widget"))

        return _run

    def test_a_supplier_row_reaches_the_response_labelled(self, run_with):
        result = run_with([_row()])

        suppliers = result["supplier_matches"]
        assert suppliers, "the stubbed supplier should have survived the matcher"

        row = suppliers[0]
        assert row.provenance == Provenance.VERIFIED.value
        assert row.provenance_label == "Verified"

    def test_an_unverified_row_is_labelled_unverified(self, run_with):
        result = run_with([_row(verified=False)])

        suppliers = result["supplier_matches"]
        assert suppliers
        assert suppliers[0].provenance == Provenance.UNVERIFIED.value
        assert suppliers[0].provenance_label == "Unverified"

    def test_the_label_survives_the_analyze_serializer(self, run_with):
        """The badge is drawn from the response payload, so the label has to
        be in it — a field the serializer drops is a field nobody reads."""
        from api.analyze import _serialize

        result = run_with([_row()])
        assert result["supplier_matches"]

        out = _serialize(result["supplier_matches"])[0]

        assert out["provenance"] == Provenance.VERIFIED.value
        assert out["provenance_label"] == "Verified"
