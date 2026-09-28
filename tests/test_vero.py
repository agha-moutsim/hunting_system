"""C5: VeRO brand check — table-driven, no network, no real catalog file.

The loader seam is monkeypatched to a known small catalog, so these tests
never depend on data/vero_brands.json being present or up to date.
"""

import pytest

import utils.vero as vero

KNOWN = {
    "brands": ["disney", "lego", "nike", "the walt disney company"],
    "generated_at": "2026-09-29",
    "loaded": True,
}


def _use(monkeypatch, catalog: dict) -> None:
    monkeypatch.setattr(vero, "_cache", catalog)


class TestRegistered:
    @pytest.mark.parametrize("query", ["Nike", "NIKE", "Nike®"])
    def test_exact_brand_after_normalisation(self, monkeypatch, query):
        _use(monkeypatch, KNOWN)
        assert vero.check_vero(query) == "registered"

    @pytest.mark.parametrize(
        "query",
        ["THE WALT DISNEY COMPANY", "Walt Disney", "Lego System A/S"],
    )
    def test_whole_token_match_in_either_direction(self, monkeypatch, query):
        _use(monkeypatch, KNOWN)
        assert vero.check_vero(query) == "registered"


class TestNotRegistered:
    @pytest.mark.parametrize("query", ["Randomxyz", "disneyx"])
    def test_absent_or_partial_name_is_not_registered(self, monkeypatch, query):
        _use(monkeypatch, KNOWN)
        assert vero.check_vero(query) == "not_registered"


class TestUnknown:
    @pytest.mark.parametrize("query", [None, "", "   "])
    def test_blank_brand_name_is_unknown(self, monkeypatch, query):
        _use(monkeypatch, KNOWN)
        assert vero.check_vero(query) == "unknown"

    def test_empty_catalog_never_guesses(self, monkeypatch):
        _use(monkeypatch, {"brands": [], "generated_at": "2026-09-29", "loaded": True})
        assert vero.check_vero("Nike") == "unknown"

    def test_missing_catalog_file_never_guesses(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vero, "VERO_FILE", tmp_path / "no_such_file.json")
        monkeypatch.setattr(vero, "_cache", None)
        assert vero.check_vero("Nike") == "unknown"


class TestCatalogInfo:
    def test_reports_loaded_catalog(self, monkeypatch):
        _use(monkeypatch, KNOWN)
        assert vero.vero_catalog_info() == {
            "count": 4,
            "generated_at": "2026-09-29",
            "loaded": True,
        }

    def test_reports_missing_catalog(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vero, "VERO_FILE", tmp_path / "no_such_file.json")
        monkeypatch.setattr(vero, "_cache", None)
        assert vero.vero_catalog_info() == {
            "count": 0,
            "generated_at": None,
            "loaded": False,
        }
