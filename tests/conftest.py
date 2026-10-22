"""Pytest path setup — existing modules live in backend/."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))


# Modules that test a supplier source ON PURPOSE, and therefore bring their own
# stubbing. Everything else gets the default.
_EXEMPT_FROM_SOURCE_GUARD = {"test_joybuy_web"}


@pytest.fixture(autouse=True)
def _no_live_supplier_sources(request, monkeypatch):
    """Stop the Joybuy web source reaching the network.

    `hunter.supplier_lookup._lookup_single_supplier` now runs Joybuy alongside
    SerpApi discovery, so every test that calls it reaches `discover_web`
    unless it says otherwise. Several of those tests stub discovery, CJ and
    AliExpress and would silently gain a live SerpApi call they never asked
    for.

    That is the same defect already fixed once in this suite: a test that
    stubs two of three sources and lets the third go live is a test whose
    result depends on the network. It showed up as a 166s suite once and a
    362s suite the next time - the same code, because SerpApi's web engine has
    a measured latency tail past 25s.

    Joybuy is stubbed here rather than per-test because discovery and AliExpress
    are stubbed per-test and this one is easy to forget. A test that genuinely
    wants a Joybuy row supplies its own, which wins because it is applied later.
    """
    module = getattr(request, "module", None)
    # pytest reports this module as "tests.test_joybuy_web", not the bare
    # filename, so the last dotted segment is what has to be compared.
    name = getattr(module, "__name__", "").rsplit(".", 1)[-1]
    if name in _EXEMPT_FROM_SOURCE_GUARD:
        return  # that module is about this source; it manages its own stubs

    from scrapers import joybuy_web

    monkeypatch.setattr(joybuy_web, "discover_web", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _hermetic_price_filters(monkeypatch):
    """Point ``utils.filters`` at a temp copy of the shipped defaults.

    ``custom_filters.json`` is a tracked file, but it is also the user's
    LIVE band-setting store: when the band is widened on the real site
    (e.g. £35 - £50), every band-derived number in the suite changes with
    it, and the run fails on tests that assert the shipped defaults. That
    is the same test-vs-environment leak the Joybuy guard above already
    exists for.

    The redirect is value-based: the temp file always carries the
    ``config.FILTERS`` defaults, so nothing a test or this fixture does
    can widen or narrow the user's real band. Modules that exercise the
    filters file on purpose (``test_filters_api``) redirect it again to
    their own target, which simply wins.
    """
    from config import FILTERS
    from utils import filters as filters_mod

    tmp = tempfile.TemporaryDirectory(prefix="hunter-filters-")
    target = Path(tmp.name) / "custom_filters.json"
    target.write_text(json.dumps({"active": dict(FILTERS), "presets": {}}))
    monkeypatch.setattr(filters_mod, "FILTERS_FILE", target)
    filters_mod._cache = {"mtime": None, "data": None}
    yield
    filters_mod._cache = {"mtime": None, "data": None}
    tmp.cleanup()