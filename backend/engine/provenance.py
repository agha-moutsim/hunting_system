"""
Provenance — CONSTRAINTS.md C13.

Every FACTUAL value the app shows carries one of four labels, and the
label is data, not a UI decision:

  verified    a real API response or a successfully parsed page
  estimated   computed by a stated, transparent method (carries `method`)
  unverified  could not be confirmed — shown, never used to gate a verdict
  ai_insight  LLM analysis — STRUCTURALLY BARRED from factual fields

`ai_insight` may never populate price, link, stock, sold count, store
name or supplier name, and never influences PASS/FAIL. This module
provides the types plus a guard that raises if that rule is broken, so a
violation is a loud error at build time instead of a silent lie on screen.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Provenance(str, Enum):
    VERIFIED = "verified"
    ESTIMATED = "estimated"
    UNVERIFIED = "unverified"
    AI_INSIGHT = "ai_insight"

    @property
    def label(self) -> str:
        return {
            Provenance.VERIFIED: "Verified",
            Provenance.ESTIMATED: "Estimated",
            Provenance.UNVERIFIED: "Unverified",
            Provenance.AI_INSIGHT: "AI Insight",
        }[self]

    @property
    def badge(self) -> str:
        return {
            Provenance.VERIFIED: "\U0001f7e2",
            Provenance.ESTIMATED: "\U0001f7e1",
            Provenance.UNVERIFIED: "⚠️",
            Provenance.AI_INSIGHT: "\U0001f916",
        }[self]


# Field names that hold FACTS. A value tagged ai_insight must never be
# written into any of these — see assert_not_ai_fact().
FACT_FIELDS = frozenset({
    "price", "item_cost", "cost", "best_supplier_price", "supplier_price",
    "url", "link", "product_link", "seller_url", "store_url",
    "stock", "inventory", "in_stock", "availability",
    "sold_count", "sold_count_30d", "sold_count_7d",
    "sold_30d", "sold_7d", "total_sold_30d", "total_sold_7d",
    "seller", "store_name", "supplier_name", "name", "full_name",
    "title", "product_title", "image_url", "brand", "condition",
    "feedback_score", "seller_rating", "seller_orders",
})


class ProvenanceError(TypeError):
    """Raised when an ai_insight value is written into a factual field."""


@dataclass
class Fact:
    """A single value with its origin attached.

    Use the constructors rather than building this by hand — they set a
    consistent `captured_at` and the right provenance for the claim.
    """
    value: Any
    provenance: Provenance
    source_url: str = ""
    method: str = ""          # required when provenance == ESTIMATED
    source_name: str = ""     # e.g. "eBay Browse API", "SerpApi", "CJ API"
    captured_at: str = ""

    def __post_init__(self):
        if isinstance(self.provenance, str):
            self.provenance = Provenance(self.provenance)
        if not self.captured_at:
            self.captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self.provenance is Provenance.ESTIMATED and not self.method:
            # C13: an estimate without a stated method is indistinguishable
            # from a guess, so we refuse to represent it as one.
            raise ProvenanceError(
                "An estimated Fact must state its method (C13)."
            )
        if self.provenance is Provenance.AI_INSIGHT:
            raise ProvenanceError(
                "AI insight is analysis, not a fact — Fact may never be "
                "constructed with provenance=ai_insight (C13)."
            )

    @property
    def is_usable_for_verdict(self) -> bool:
        """Only verified/estimated evidence may decide PASS/FAIL."""
        return self.provenance in (Provenance.VERIFIED, Provenance.ESTIMATED)

    @property
    def label(self) -> str:
        return self.provenance.label

    @property
    def badge(self) -> str:
        return self.provenance.badge

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "provenance": self.provenance.value,
            "label": self.provenance.label,
            "source_url": self.source_url,
            "method": self.method,
            "source_name": self.source_name,
            "captured_at": self.captured_at,
        }


# ---------------------------------------------------------------- constructors

def verified(value: Any, source_url: str = "", source_name: str = "") -> Fact:
    """A value read straight from an API or a parsed page."""
    return Fact(value=value, provenance=Provenance.VERIFIED,
                source_url=source_url, source_name=source_name)


def estimated(value: Any, method: str, source_url: str = "",
              source_name: str = "") -> Fact:
    """A value COMPUTED by a named, reproducible method."""
    return Fact(value=value, provenance=Provenance.ESTIMATED, method=method,
                source_url=source_url, source_name=source_name)


def unverified(value: Any = None, source_url: str = "",
               source_name: str = "", reason: str = "") -> Fact:
    """A value we could not confirm. Shown, never gates a verdict."""
    return Fact(value=value, provenance=Provenance.UNVERIFIED,
                source_url=source_url, source_name=source_name,
                method=reason)


# ---------------------------------------------------------------- guards

def assert_not_ai_fact(value: Any, field_name: str) -> None:
    """Raise if an AI-insight marker is found in a factual field (C13).

    Facts are never tagged ai_insight (Fact.__post_init__ refuses), so this
    is a belt-and-braces check for dict payloads arriving from the LLM
    before they are merged into a result.
    """
    if isinstance(value, dict):
        prov = str(value.get("provenance", "")).lower()
        if prov == Provenance.AI_INSIGHT.value:
            # A violation exists either because the CALLER named a factual
            # field, or because this object itself contains factual keys —
            # both shapes show up once payloads pass through lists.
            if field_name in FACT_FIELDS or any(k in FACT_FIELDS for k in value):
                raise ProvenanceError(
                    f"C13 violation: field '{field_name}' is a factual field "
                    f"and cannot carry ai_insight provenance."
                )
        for k, v in value.items():
            assert_not_ai_fact(v, k)
    elif isinstance(value, list):
        for item in value:
            assert_not_ai_fact(item, field_name)


def annotate(payload: dict, provenance: Provenance, source_url: str = "",
             source_name: str = "", method: str = "") -> dict:
    """Attach provenance keys to an existing result dict.

    Used by exporters and API serializers so a row built before this change
    still reports where it came from.
    """
    payload["provenance"] = provenance.value
    payload["provenance_label"] = provenance.label
    if source_url:
        payload["source_url"] = source_url
    if source_name:
        payload["source_name"] = source_name
    if method:
        payload["method"] = method
    return payload


def classify(verified_value: bool, value: Any = None, **kw) -> Fact:
    """Shim for older call sites holding a bare bool `verified` flag."""
    return verified(value, **kw) if verified_value else unverified(value, **kw)


def stamp_scraped_product(row: Any) -> Any:
    """Fill a ScrapedProduct's provenance from its `verified` flag (C13).

    ScrapedProduct carried only `verified: bool` — no label — so every
    consumer that drew a badge from `provenance` drew nothing at all, and a
    row read off a real API or a parsed page reached the screen unlabelled.
    The label is data, so it is derived here rather than in the frontend.

    Never overwrites a stamp the row already carries: an explicit label from
    the scraper that read it wins over this derivation.
    """
    if row is None:
        return row
    if getattr(row, "provenance", ""):
        return row
    prov = Provenance.VERIFIED if getattr(row, "verified", True) else Provenance.UNVERIFIED
    row.provenance = prov.value
    row.provenance_label = prov.label
    return row
