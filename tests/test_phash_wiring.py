"""C14's image phash — from URL to score, across every consumer.

ZERO NETWORK: `requests.get` is replaced for the whole file. Images are
generated locally with PIL, so the hash is real and the test is offline.

Two properties matter more than the hashing itself:

  * a reference hash is REQUIRED before any candidate image is downloaded —
    with no eBay image there is nothing to compare a supplier image against,
    so fetching one would be pure cost;
  * an image that cannot be read yields None and the score loses that
    component, never gains a fabricated one (C1/C13).
"""

from __future__ import annotations

import io

import pytest
import requests

import analysis_pipeline as ap
import deep_search as ds
import pipeline as pipeline_mod
from engine.match import (
    MATCH_METHOD,
    clear_image_hash_cache,
    compute_match,
    image_hash_for,
)
from hunter import supplier_lookup as sl
from scrapers.base import ScrapedProduct


# ---------------------------------------------------------------------------
# Local images — real bytes, real pHash, no network
# ---------------------------------------------------------------------------

def _png(seed: int) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 64))
    px = img.load()
    for x in range(64):
        for y in range(64):
            px[x, y] = ((x * seed) % 256, (y * seed) % 256, ((x + y) * seed) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


EBAY_PNG = _png(7)
SUPPLIER_PNG = _png(7)   # the SAME picture -> identical hash
OTHER_PNG = _png(200)    # a different picture

REF_TITLE = "Bosch 18V Cordless Combi Drill 2 x 4.0Ah"
REF_PRICE = 95.0


class _ImgResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _ImageServer:
    """Stands in for requests.get; only serves URLs it was given."""

    def __init__(self, images: dict[str, bytes]) -> None:
        self.images = images
        self.requested: list[str] = []

    def __call__(self, url, **kwargs):
        self.requested.append(url)
        if url in self.images:
            return _ImgResponse(self.images[url])
        raise requests.RequestException(f"no image at {url}")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Block the network for the whole file unless a test installs a server."""
    clear_image_hash_cache()

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted - this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    yield
    clear_image_hash_cache()


def _serve(monkeypatch, images: dict[str, bytes]) -> _ImageServer:
    server = _ImageServer(images)
    monkeypatch.setattr(requests, "get", server)
    return server


def _product(url="https://img.example.com/supplier.jpg", title=REF_TITLE) -> ScrapedProduct:
    return ScrapedProduct(
        source="Toolstation",
        title=title,
        price=89.99,
        url="https://www.toolstation.com/p1",
        image_url=url,
    )


# ---------------------------------------------------------------------------
# image_hash_for — the leaf
# ---------------------------------------------------------------------------

class TestImageHashFor:
    @pytest.mark.parametrize("url", [None, "", "   ", 123, object()])
    def test_no_usable_url_returns_none_without_a_request(self, monkeypatch, url):
        server = _serve(monkeypatch, {"https://x/a.jpg": EBAY_PNG})

        assert image_hash_for(url) is None
        assert server.requested == []

    def test_a_readable_image_yields_a_hash(self, monkeypatch):
        _serve(monkeypatch, {"https://x/a.jpg": EBAY_PNG})

        assert isinstance(image_hash_for("https://x/a.jpg"), int)

    def test_the_same_picture_hashes_the_same_way(self, monkeypatch):
        _serve(monkeypatch, {"https://x/a.jpg": EBAY_PNG, "https://x/b.jpg": SUPPLIER_PNG})

        assert image_hash_for("https://x/a.jpg") == image_hash_for("https://x/b.jpg")

    def test_a_different_picture_hashes_differently(self, monkeypatch):
        _serve(monkeypatch, {"https://x/a.jpg": EBAY_PNG, "https://x/b.jpg": OTHER_PNG})

        a = image_hash_for("https://x/a.jpg")
        b = image_hash_for("https://x/b.jpg")
        assert a != b

    def test_the_url_is_fetched_once_and_then_cached(self, monkeypatch):
        server = _serve(monkeypatch, {"https://x/a.jpg": EBAY_PNG})

        first = image_hash_for("https://x/a.jpg")
        second = image_hash_for("https://x/a.jpg")

        assert first == second
        assert server.requested == ["https://x/a.jpg"]

    def test_an_unreachable_image_is_none_not_an_exception(self, monkeypatch):
        server = _serve(monkeypatch, {})  # every URL 404s

        assert image_hash_for("https://x/missing.jpg") is None
        assert len(server.requested) == 1

    def test_a_dead_host_is_not_retried_for_every_row(self, monkeypatch):
        server = _serve(monkeypatch, {})

        assert image_hash_for("https://x/missing.jpg") is None
        assert image_hash_for("https://x/missing.jpg") is None

        # Cached failure: one request, not one per row.
        assert len(server.requested) == 1

    def test_bytes_that_are_not_an_image_yield_none(self, monkeypatch):
        _serve(monkeypatch, {"https://x/a.jpg": b"<html>not an image</html>"})

        assert image_hash_for("https://x/a.jpg") is None


# ---------------------------------------------------------------------------
# The phash actually reaches the score
# ---------------------------------------------------------------------------

class TestPhashReachesTheScore:
    def test_both_images_present_adds_the_component(self):
        result = compute_match(
            REF_TITLE, REF_TITLE,
            ebay_price=REF_PRICE, candidate_price=89.99,
            ebay_image_hash=1, candidate_image_hash=1,
        )
        assert "phash" in result.components
        assert result.components["phash"] == pytest.approx(1.0)

    def test_identical_images_raise_a_moderately_similar_score(self):
        weak_ref = "Bosch drill 18 volt"
        weak_cand = "Bosch 18v combi drill bare unit"

        without = compute_match(
            weak_ref, weak_cand, ebay_price=REF_PRICE, candidate_price=89.99
        )
        with_same = compute_match(
            weak_ref, weak_cand, ebay_price=REF_PRICE, candidate_price=89.99,
            ebay_image_hash=1, candidate_image_hash=1,
        )

        assert with_same.score > without.score
        assert "phash" not in without.components

    def test_an_unknown_image_on_either_side_excludes_the_component(self):
        result = compute_match(
            REF_TITLE, REF_TITLE,
            ebay_price=REF_PRICE, candidate_price=89.99,
            ebay_image_hash=1, candidate_image_hash=None,
        )
        assert "phash" not in result.components


# ---------------------------------------------------------------------------
# The cost rule: no reference hash -> no download
# ---------------------------------------------------------------------------

class TestNoReferenceHashMeansNoDownload:
    def test_score_supplier_fetches_nothing_without_a_reference_hash(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = _product()

        ap._score_supplier(row, REF_TITLE, REF_PRICE)   # no ebay_image_hash

        assert server.requested == []
        assert row.image_hash is None

    def test_match_gate_fetches_nothing_without_a_reference_hash(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})

        pipeline_mod._match_gate([_product()], REF_TITLE, REF_PRICE)

        assert server.requested == []

    def test_first_valid_fetches_nothing_without_a_reference_hash(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})

        sl._first_valid([_product()], REF_TITLE, REF_PRICE)

        assert server.requested == []

    def test_gate_suppliers_fetches_nothing_without_a_reference_hash(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = {"title": REF_TITLE, "price": 89.99,
               "url": "https://x/p", "image_url": "https://img.example.com/supplier.jpg"}

        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)

        assert server.requested == []


# ---------------------------------------------------------------------------
# Each consumer passes the reference hash through
# ---------------------------------------------------------------------------

_TITLE_ONLY = "Bosch 18V cordless combi drill bare unit"


class TestConsumersPassTheReferenceHash:
    def test_score_supplier_hashes_the_candidate_and_scores_with_it(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = _product()

        ap._score_supplier(row, _TITLE_ONLY, REF_PRICE, ebay_image_hash=12345)

        assert server.requested == ["https://img.example.com/supplier.jpg"]
        assert row.image_hash is not None
        assert row.match_method == MATCH_METHOD

    def test_score_supplier_result_matches_a_direct_call(self, monkeypatch):
        _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = _product()

        ap._score_supplier(row, _TITLE_ONLY, REF_PRICE, ebay_image_hash=12345)

        expected = compute_match(
            _TITLE_ONLY, REF_TITLE,
            ebay_price=REF_PRICE, candidate_price=89.99,
            ebay_image_hash=12345, candidate_image_hash=row.image_hash,
        )
        assert row.match_score == expected.score
        assert "phash" in expected.components

    def test_match_gate_hashes_candidates_when_given_a_reference(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = _product()

        pipeline_mod._match_gate([row], _TITLE_ONLY, REF_PRICE, ebay_image_hash=777)

        assert server.requested == ["https://img.example.com/supplier.jpg"]
        assert row.image_hash is not None

    def test_first_valid_hashes_candidates_when_given_a_reference(self, monkeypatch):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = _product()

        sl._first_valid([row], _TITLE_ONLY, REF_PRICE, ebay_image_hash=777)

        assert server.requested == ["https://img.example.com/supplier.jpg"]
        assert row.image_hash is not None

    def test_gate_suppliers_hashes_dict_rows_when_given_a_reference(
        self, monkeypatch
    ):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = {"title": REF_TITLE, "price": 89.99, "url": "https://x/p",
               "image_url": "https://img.example.com/supplier.jpg",
               "product_title": REF_TITLE}

        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE,
                           ebay_image_hash=777)

        assert server.requested == ["https://img.example.com/supplier.jpg"]
        assert row["image_hash"] is not None

    def test_gate_suppliers_does_not_rehash_a_row_that_already_has_one(
        self, monkeypatch
    ):
        server = _serve(monkeypatch, {"https://img.example.com/supplier.jpg": SUPPLIER_PNG})
        row = {"title": REF_TITLE, "price": 89.99, "url": "https://x/p",
               "image_url": "https://img.example.com/supplier.jpg",
               "product_title": REF_TITLE, "image_hash": 4242}

        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE,
                           ebay_image_hash=777)

        assert server.requested == []
        assert row["image_hash"] == 4242


# ---------------------------------------------------------------------------
# The reference image itself
# ---------------------------------------------------------------------------

class TestReferenceImageHash:
    def test_no_sold_data_means_no_reference_hash(self):
        assert ds._reference_image_hash(None) is None

    def test_an_object_with_no_items_means_no_reference_hash(self):
        class _Empty:
            items = []

        assert ds._reference_image_hash(_Empty()) is None

    def test_it_uses_a_real_ebay_listing_image(self, monkeypatch):
        _serve(monkeypatch, {"https://i.ebayimg.com/1.jpg": EBAY_PNG})

        class _Item:
            image_url = "https://i.ebayimg.com/1.jpg"

        class _Sold:
            items = [_Item()]

        assert isinstance(ds._reference_image_hash(_Sold()), int)

    def test_it_skips_items_with_no_image(self, monkeypatch):
        _serve(monkeypatch, {"https://i.ebayimg.com/2.jpg": EBAY_PNG})

        class _NoImage:
            image_url = None

        class _HasImage:
            image_url = "https://i.ebayimg.com/2.jpg"

        class _Sold:
            items = [_NoImage(), _NoImage(), _HasImage()]

        assert isinstance(ds._reference_image_hash(_Sold()), int)

    def test_it_gives_up_rather_than_raising_when_images_unreadable(self, monkeypatch):
        _serve(monkeypatch, {})  # every image URL fails

        class _Item:
            image_url = "https://i.ebayimg.com/1.jpg"

        class _Sold:
            items = [_Item()]

        assert ds._reference_image_hash(_Sold()) is None
