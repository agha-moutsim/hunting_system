"""Phase D - the AU supplier bench is AliExpress + CJ, never the UK retailers.

These tests are offline: every scraper class is replaced before the pipeline
imports it, and SerpApi discovery is a stub. The point is the source list and
the Google scope, not a live price.
"""

from __future__ import annotations

import asyncio

from scrapers.base import ScrapedProduct


class _StubScraper:
    source = ""
    price = 10.0

    def __init__(self):
        self.closed = False

    async def search(self, query):
        return [ScrapedProduct(
            source=self.source,
            title=query,
            price=self.price,
            url=f"https://example.test/{self.source.lower().replace(' ', '-')}",
            condition="",
            verified=True,
        )]

    async def close(self):
        self.closed = True


class _AliScraper(_StubScraper):
    source = "AliExpress"


class _CJScraper(_StubScraper):
    source = "CJ Dropshipping"


class _Forbidden:
    def __init__(self, *args, **kwargs):
        raise AssertionError("a UK retailer was instantiated for AU")


def test_au_searches_only_aliexpress_and_cj(monkeypatch):
    import analysis_pipeline as ap
    import scrapers.aliexpress as ae
    import scrapers.bandq as bq
    import scrapers.cjdropshipping as cj
    import scrapers.toolstation as ts
    from scrapers import serpapi_discovery as sd

    monkeypatch.setattr(ae, "AliExpressScraper", _AliScraper)
    monkeypatch.setattr(cj, "CJDropshippingScraper", _CJScraper)
    monkeypatch.setattr(bq, "BandQScraper", _Forbidden)
    monkeypatch.setattr(ts, "ToolstationScraper", _Forbidden)

    seen = {}

    def _discover(query, marketplace="EBAY_GB"):
        seen["marketplace"] = marketplace
        return []

    monkeypatch.setattr(sd, "discover", _discover)

    rows = asyncio.run(
        ap.search_all_suppliers("cordless drill", marketplace="EBAY_AU")
    )

    assert {row.source for row in rows} == {"AliExpress", "CJ Dropshipping"}
    assert seen["marketplace"] == "EBAY_AU"


def test_uk_still_searches_its_retail_bench(monkeypatch):
    import analysis_pipeline as ap
    import scrapers.aliexpress as ae
    import scrapers.bandq as bq
    import scrapers.cjdropshipping as cj
    import scrapers.toolstation as ts
    from scrapers import serpapi_discovery as sd

    class _BandQ(_StubScraper):
        source = "B&Q"

    class _Toolstation(_StubScraper):
        source = "Toolstation"

    monkeypatch.setattr(ae, "AliExpressScraper", _AliScraper)
    monkeypatch.setattr(cj, "CJDropshippingScraper", _CJScraper)
    monkeypatch.setattr(bq, "BandQScraper", _BandQ)
    monkeypatch.setattr(ts, "ToolstationScraper", _Toolstation)

    seen = {}

    def _discover(query):
        seen["called"] = True
        return []

    monkeypatch.setattr(sd, "discover", _discover)

    rows = asyncio.run(ap.search_all_suppliers("cordless drill"))

    assert {row.source for row in rows} == {
        "AliExpress", "CJ Dropshipping", "B&Q", "Toolstation"
    }
    assert seen["called"] is True
