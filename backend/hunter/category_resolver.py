"""Resolve the text a user typed into a real eBay query.

REGRESSION-001 (2026-10-02): the user typed "garden tools" and received
electronics. The cause was one line in `category_scan.scan_category`:

    category_id = EBAY_CATEGORIES.get(category_name, "293")

an exact, case-sensitive lookup whose fallback was Electronics — and no
`q` was ever sent to eBay, so the typed words were discarded entirely. Every
unrecognised input silently became category 293 while the rows were stamped
with the user's own text, so the page read "garden tools" above a shelf of
electronics.

The rule is deliberately boring, because a surprising one is what caused the
bug in the first place:

    * the text matches one of the known category names (ignoring case and
      surrounding space) -> browse that category;
    * anything else -> search eBay for exactly those words.

No guessing, no "closest" category, no silent substitution. A search we do
not recognise is searched; it is never turned into a different question.
"""

from __future__ import annotations

from dataclasses import dataclass

# The categories we can browse. Kept here (not in category_scan) so the
# resolver is the single place that decides what a piece of text means.
EBAY_CATEGORIES: dict[str, str] = {
    "Electronics": "293",
    "Home & Garden": "1173",
    "Clothing, Shoes & Accessories": "11450",
    "Sports & Outdoors": "888",
    "Toys & Hobbies": "220",
    "Health & Beauty": "2610",
    "Automotive": "9800",
    "Pet Supplies": "1281",
    "Baby Essentials": "263955",
    "Jewellery & Watches": "281",
    "Business & Industrial": "12576",
    "Cameras & Photo": "625",
    "Computers/Tablets": "580581",
    "Musical Instruments": "619",
    "Collectibles": "1",
}

# lower-cased label -> canonical label, so matching ignores case and padding.
_BY_LOWER: dict[str, str] = {label.lower(): label for label in EBAY_CATEGORIES}

MODE_CATEGORY = "category"
MODE_KEYWORD = "keyword"


@dataclass(frozen=True)
class ResolvedSearch:
    """What to actually ask eBay for.

    `text`   the cleaned search text
    `mode`   MODE_CATEGORY (browse `category_id`) or MODE_KEYWORD (search `text`)
    `label`  the category the user picked, or "" when free text
    `reason` one line saying which rule decided it, for the response notes
    """

    text: str
    mode: str
    category_id: str = ""
    label: str = ""
    reason: str = ""

    @property
    def is_category(self) -> bool:
        return self.mode == MODE_CATEGORY


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def resolve_category(text: str) -> ResolvedSearch:
    """Decide whether `text` names a known category or is a free-text search."""
    cleaned = _clean(text)

    if not cleaned:
        return ResolvedSearch(
            text="", mode=MODE_KEYWORD,
            reason="no search text supplied",
        )

    label = _BY_LOWER.get(cleaned.lower())
    if label:
        return ResolvedSearch(
            text=label, mode=MODE_CATEGORY, category_id=EBAY_CATEGORIES[label],
            label=label, reason=f"matched category '{label}'",
        )

    return ResolvedSearch(
        text=cleaned, mode=MODE_KEYWORD,
        reason=f"'{cleaned}' is not one of the {len(EBAY_CATEGORIES)} known "
               "categories - searching eBay for those words instead",
    )


def category_choices() -> list[dict[str, str]]:
    """The categories the UI offers, for the dropdown."""
    return [
        {"label": label, "category_id": category_id}
        for label, category_id in EBAY_CATEGORIES.items()
    ]
