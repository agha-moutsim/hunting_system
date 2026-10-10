"""Store IDENTITY, not store COUNT — the /str/ vs /usr/ conflation.

Root cause (see docs/plans/2026-10-10-store-integrity.md):

eBay has TWO identifiers and the code treated them as one.

    seller user ID   ->  ebay.co.uk/usr/{username}   always exists
    store URL slug   ->  ebay.co.uk/str/{slug}       exists only if the
                                                    seller set one

`stores.py` fabricated `/str/{username}`. When a seller's slug differs from
their username — the common case — that link is a dead "Store not found".
The old code still stamped those rows `provenance="verified"`, and the UI
rendered a `derived` chip beside a `Verified` badge on the same row.

These tests replace assertions that encoded that defect. They run OFFLINE:
nothing here may reach eBay, because the fix must not depend on a request
(the host is served a CAPTCHA for /str/ anyway — proven by negative control).

Run with: python -m pytest tests/test_store_identity.py -q
"""

from __future__ import annotations

import pytest

from config import EBAY_UK_BASE
from engine.stores import (
    build_stores,
    seller_profile_url,
    store_provenance_block,
    store_url_from_observed_slug,
    stores_from_items,
)
from scrapers.ebay_sold import EbaySoldItem, EbaySoldScraper


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """Identity must be decided from data we already hold."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


def _item(seller, price=10.0, store_url=""):
    return EbaySoldItem(
        title="Generic widget", price=price,
        url="https://www.ebay.co.uk/itm/1", seller=seller,
        seller_url=seller_profile_url(seller), sold_date="",
        store_url=store_url,
    )


# ---------------------------------------------------------------------------
# The two identifiers are different things
# ---------------------------------------------------------------------------

class TestTheTwoIdentifiersAreDistinct:

    def test_seller_profile_url_is_the_usr_form(self):
        assert seller_profile_url("good_store") == f"{EBAY_UK_BASE}/usr/good_store"

    def test_store_url_needs_a_slug_we_actually_saw(self):
        assert store_url_from_observed_slug("MyBrandShop") == \
            f"{EBAY_UK_BASE}/str/MyBrandShop"

    def test_a_username_is_never_silently_promoted_to_a_store_slug(self):
        """The exact defect: /str/ built from a user ID."""
        username = "har_476199"
        # Building the profile is legitimate...
        assert "/str/" not in seller_profile_url(username)
        # ...but there must be NO function that manufactures a /str/ URL from
        # a username alone. The store builder is the only /str/ producer and
        # it is only ever called with an observed slug.
        assert store_url_from_observed_slug(username).startswith(f"{EBAY_UK_BASE}/str/")
        # The distinction only exists if callers choose correctly, which the
        # row tests below enforce.

    @pytest.mark.parametrize("junk", ["", "   ", None, "a/b", "a b"])
    def test_no_identifier_no_url(self, junk):
        assert seller_profile_url(junk) == ""
        assert store_url_from_observed_slug(junk) == ""


# ---------------------------------------------------------------------------
# The row: observed store beats profile fallback
# ---------------------------------------------------------------------------

class TestRowPrefersAnObservedStore:

    def test_observed_store_url_is_used_verbatim(self):
        rows = stores_from_items([
            _item("someone", store_url="https://www.ebay.co.uk/str/MyBrandShop"),
        ])
        assert rows[0]["url"] == "https://www.ebay.co.uk/str/MyBrandShop"
        assert rows[0]["url_kind"] == "observed"
        assert rows[0]["url_derived"] is False
        assert rows[0]["provenance"] == "verified"

    def test_without_an_observed_store_it_falls_back_to_the_seller_profile(self):
        rows = stores_from_items([_item("someone")])
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/usr/someone"
        assert rows[0]["url_kind"] == "seller_profile"
        assert rows[0]["url_derived"] is True

    def test_a_profile_row_is_not_presented_as_a_confirmed_storefront(self):
        rows = stores_from_items([_item("someone")])
        assert rows[0]["provenance"] == "unverified"
        assert "storefront" in rows[0]["provenance_reason"].lower()

    def test_no_emitted_row_ever_carries_a_str_url_it_did_not_observe(self):
        """The regression guard for the whole bug class."""
        rows = stores_from_items([_item("seller_one"), _item("seller_two")])
        for row in rows:
            if "/str/" in row["url"]:
                assert row["url_kind"] == "observed", (
                    f"{row['url']} was fabricated from a username"
                )

    def test_build_stores_takes_an_optional_observed_url(self):
        rows = build_stores(
            [("acme", 3, 12.0)],
            observed_store_urls={"acme": "https://www.ebay.co.uk/str/acme-shop"},
        )
        assert rows[0]["url"] == "https://www.ebay.co.uk/str/acme-shop"
        assert rows[0]["url_kind"] == "observed"

    def test_duplicate_sellers_keep_the_observed_url_of_the_first(self):
        rows = stores_from_items([
            _item("dupe", store_url="https://www.ebay.co.uk/str/RealShop"),
            _item("dupe"),
        ])
        assert len(rows) == 1
        assert rows[0]["url"] == "https://www.ebay.co.uk/str/RealShop"
        assert rows[0]["sold_count"] == 2


# ---------------------------------------------------------------------------
# The scraper must stop discarding the anchor eBay already rendered
# ---------------------------------------------------------------------------

SOLD_PAGE = """
<html><body><ul>
  <li class="s-item">
    <div class="s-item__title"><span>Widget one</span></div>
    <span class="s-item__price">GBP 12.00</span>
    <a class="s-item__link" href="https://www.ebay.co.uk/itm/1"></a>
    <div class="s-item__seller-info">
      <span class="s-item__seller-info-text">
        <a href="https://www.ebay.co.uk/str/MyBrandShop">MyBrandShop</a>
      </span>
    </div>
    <span class="s-item__condition">New</span>
  </li>
  <li class="s-item">
    <div class="s-item__title"><span>Widget two</span></div>
    <span class="s-item__price">GBP 14.00</span>
    <a class="s-item__link" href="https://www.ebay.co.uk/itm/2"></a>
    <div class="s-item__seller-info">
      <span class="s-item__seller-info-text">plain_seller_778</span>
    </div>
    <span class="s-item__condition">New</span>
  </li>
</ul></body></html>
"""


def _parse(html: str):
    from bs4 import BeautifulSoup
    return EbaySoldScraper()._parse_sold_page(BeautifulSoup(html, "html.parser"))


class TestScraperKeepsWhatItWasGiven:

    def test_an_observed_store_anchor_is_captured(self):
        items = _parse(SOLD_PAGE)
        assert items[0].seller == "MyBrandShop"
        assert items[0].store_url == "https://www.ebay.co.uk/str/MyBrandShop"

    def test_a_plain_seller_name_gets_a_profile_link_not_a_store_link(self):
        items = _parse(SOLD_PAGE)
        assert items[1].seller == "plain_seller_778"
        assert items[1].store_url == ""
        assert items[1].seller_url == f"{EBAY_UK_BASE}/usr/plain_seller_778"

    def test_a_store_url_is_emitted_only_when_it_was_observed(self):
        """The invariant, precisely: a /str/ href may appear ONLY when the
        same href was read off the page. Never manufactured from a username.
        """
        for item in _parse(SOLD_PAGE):
            if "/str/" in item.seller_url:
                assert item.store_url, (
                    f"fabricated a storefront with no observation: "
                    f"{item.seller_url}"
                )
                assert item.seller_url == item.store_url
            else:
                assert "/str/" not in item.seller_url

    def test_a_missing_seller_yields_neither_identifier(self):
        html = """
        <html><body><ul><li class="s-item">
          <div class="s-item__title"><span>Orphan</span></div>
          <span class="s-item__price">GBP 9.00</span>
          <span class="s-item__condition">New</span>
        </li></ul></body></html>
        """
        items = _parse(html)
        assert items[0].seller == ""
        assert items[0].seller_url == ""
        assert items[0].store_url == ""


# ---------------------------------------------------------------------------
# The block stamp must not contradict the rows beneath it
# ---------------------------------------------------------------------------

class TestBlockStampAgreesWithItsRows:
    """REGRESSION-007, second half.

    A live Phase 7 run showed the block stamped `verified` while every row
    under it read `unverified`. The count was real, but "verified" implied the
    storefronts were confirmed, which they were not. The block may never be
    stronger than the rows it describes.
    """

    def _rows(self, observed: bool):
        return stores_from_items([
            _item("alpha", store_url=f"{EBAY_UK_BASE}/str/Alpha" if observed else ""),
        ] * 4 if not observed else [
            _item(n, store_url=f"{EBAY_UK_BASE}/str/{n}")
            for n in ("a1", "b2", "c3", "d4")
        ])

    def test_block_is_unverified_when_no_storefront_is_confirmed(self):
        rows = stores_from_items([_item("alpha")])
        block = store_provenance_block(rows)
        assert block["provenance"] == "unverified"
        assert "storefront" in block["reason"].lower()

    def test_block_may_be_verified_only_when_every_row_is_a_confirmed_store(self):
        rows = stores_from_items([
            _item(n, store_url=f"{EBAY_UK_BASE}/str/{n}")
            for n in ("a1", "b2", "c3", "d4")
        ])
        block = store_provenance_block(rows)
        assert all(r["provenance"] == "verified" for r in rows)
        assert block["provenance"] == "verified"

    def test_block_is_never_stronger_than_its_weakest_row(self):
        mixed = stores_from_items([
            _item("a1", store_url=f"{EBAY_UK_BASE}/str/a1"),
            _item("b2", store_url=f"{EBAY_UK_BASE}/str/b2"),
            _item("c3"),
            _item("d4"),
        ])
        block = store_provenance_block(mixed)
        assert block["provenance"] == "unverified"