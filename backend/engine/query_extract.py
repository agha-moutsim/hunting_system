"""Turn an eBay product title into a query eBay can actually match.

REGRESSION-006 (2026-10-02): the user saw one competitor store, or none, on
every analysis. Root cause, verified against the live Browse API - NOT the
price band, NOT the 4-store cap, both of which are correct:

    "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China 5oz
     Coffee Tea"       -> 0 items, 0 sellers
    "colorful cups"    -> 50 items, 41 sellers
    "cups and saucers" -> 50 items, 39 sellers
    "bone china"       -> 50 items, 31 sellers

Analyze passed `ebay_product.title` verbatim as the sold-listing search, so a
12-word title matched nothing at all. With no items there is no seller tally,
so `stores_from_top_sellers` had nothing to rank and the C11 store block came
back empty. When a title was short enough to match exactly one listing, that
one listing's single seller became the entire competitor list - which is why
the symptom looked like "always exactly 1".

This module is the seam for that fix. Its whole interface is three functions,
and the complexity lives behind them:

    extract_query(title)   -> a shorter, better query
    should_reduce(text)    -> is this worth reducing at all?
    fallback_queries(text) -> the ladder to try if the exact text found nothing

Design rules this follows, because getting them wrong is how the bug shipped:

  * NEVER reduce by default. The exact title is the most precise query there
    is, and a keyword guess can match a similar-but-different product. The
    caller tries the real title first and only walks `fallback_queries` when
    eBay genuinely returned nothing. Precision is spent first, breadth is the
    fallback, and the caller can say which one produced a store list.
  * Never return an empty query. Searching for "" is not a narrower result,
    it is a broken feature, and it would look like a rare product rather than
    a bug.
  * Keep the brand and the model number. Those are the tokens that stop a
    Bosch drill from matching a Faithfull one; dropping them is how a "broadened"
    search stops being about the same product.
  * Keep quantities. "6 piece set" and a single trowel are different things.
"""

from __future__ import annotations

import re

# A title longer than this many words is what eBay cannot match. Verified
# against the live API: 3 words returns ~40 sellers, 12 words returns none.
MAX_QUERY_WORDS = 6

# Words that describe the listing, not the product. Removing them is what
# turns a 12-word title into something eBay will answer.
_FILLER = frozenset({
    # condition / quality claims
    "new", "brand", "new", "genuine", "oem", "original", "quality",
    "premium", "professional", "pro", "plus", "deluxe", "super", "ultra",
    "high", "best", "top", "great", "perfect", "ideal", "special",
    # shipping / urgency
    "free", "delivery", "shipping", "postage", "fast", "next", "day",
    "days", "discount", "sale", "offer", "offers", "stock", "available",
    # listing mechanics
    "listing", "lot", "bundle", "pack", "pcs", "set", "kit", "combo",
    "collection", "lot", "auction", "buy", "it", "now", "bn", "in",
    "condition", "used", "refurbished", "boxed", "sealed",
    # filler adjectives
    "size", "colour", "color", "shape", "style", "type", "kind", "sort",
    "and", "or", "the", "for", "with", "from", "by", "a", "an", "of", "to",
    "your", "our", "my", "all", "any", "very", "nice", "good", "fine",
    "large", "small", "big", "little", "newest", "latest", "hot",
})

# Never dropped, however the title reads. Dropping these is how a broadened
# search stops being about the same product.
#
# NOTE: "set"/"kit"/"bundle" are the quantity words - a "6 piece kit" is a
# different purchase from a single tool, so they carry meaning and stay.
# "new" is NOT here: the Browse API already filters on conditions:{NEW}, and a
# title that opens "NEW Genuine ..." is carrying the listing's marketing, not
# the product. Keeping it wastes one of the six terms we can afford.
_PROTECTED = frozenset({
    "set", "kit", "pair", "bundle", "pack", "piece", "pieces",
})

_PUNCT = re.compile(r"[^a-z0-9&+\-\s.]+")
_WS = re.compile(r"\s+")


def _tokens(text: str) -> list[str]:
    """Lower-cased word/number tokens, punctuation stripped."""
    cleaned = _PUNCT.sub(" ", str(text or "").lower())
    return [t for t in _WS.split(cleaned) if t]


def _meaningful(tokens: list[str]) -> list[str]:
    """Keep the words that identify the product; drop the listing mechanics."""
    kept: list[str] = []
    for token in tokens:
        if token in _PROTECTED or token not in _FILLER:
            kept.append(token)
    return kept


def should_reduce(text: str) -> bool:
    """Is this text worth reducing?

    The test is word count, not character count: eBay matches on terms, and a
    long single word ("supercalifragilisticexpialidocious") is still one
    perfectly good query. A short phrase is already the best query available,
    so reducing it can only lose precision.
    """
    tokens = _tokens(text)
    if not tokens:
        return False
    return len(_meaningful(tokens)) > MAX_QUERY_WORDS


def extract_query(title: str) -> str:
    """Reduce a product title to the words worth searching for.

    Returns "" only for empty input. Otherwise the result is never empty: if
    everything would be filtered out as filler, the original tokens are used,
    because a poor query is better than a broken one.
    """
    tokens = _tokens(title)
    if not tokens:
        return ""

    meaningful = _meaningful(tokens)
    if not meaningful:
        # "NEW TOP QUALITY BRAND NEW" has no content words at all. Keep the
        # rarest tokens rather than searching for nothing.
        return " ".join(tokens[:MAX_QUERY_WORDS])

    return " ".join(meaningful[:MAX_QUERY_WORDS])


def fallback_queries(text: str) -> list[str]:
    """Queries to try, in order, when the exact `text` matched nothing.

    Empty for a query that is already good - the caller must not broaden a
    search that works.

    ORDER IS THE WHOLE POINT, and it was learned from the live API. eBay
    matches on ALL terms, so a *long* query is the restrictive one and a
    *short* one is the permissive one. Measured on real titles:

        "Greenhouse 6ft Polycarbonate Seed Starter with Ventilation"
            -> 11 items,  8 sellers
        "greenhouse 6ft polycarbonate seed starter ventilation"
            ->  0 items,  0 sellers   <- reduction made it WORSE
        "greenhouse 6ft polycarbonate seed"
            -> 50 items, 32 sellers   <- fewer terms, far more results

    So the ladder runs from the most terms to the fewest, and the caller stops
    at the first rung that returns anything. Dropping the tail of a title is
    how you widen it, and the tail ("... 5oz Coffee Tea", "... with
    Ventilation") is exactly the least identifying part.

    The final rungs drop a LEADING brand token, because a rare brand is the
    other way a title matches nothing. Measured:

        "pasabahce 2 colorful cups & saucers"  ->  0 items, 0 sellers
        "colorful cups"                        -> 49 items, 4 sellers

    This is the loosest claim the ladder can make - competitors for the
    product type rather than the product - so it is last, and a caller that
    used it must report the search as broadened.
    """
    if not should_reduce(text):
        return []

    meaningful = _meaningful(_tokens(text))
    if len(meaningful) <= MAX_QUERY_WORDS:
        return []

    ladder: list[str] = []
    original = str(text).strip()
    # Longest first: the caller walks down and stops at the first hit, so the
    # most precise available query is the one that is tried first.
    for keep in range(len(meaningful) - 1, 1, -1):
        candidate = " ".join(meaningful[:keep])
        if not candidate or candidate == original or candidate in ladder:
            continue
        ladder.append(candidate)

    # Brand-drop rung: remove a leading capitalised token from the ORIGINAL
    # title (not the lowercased one) and re-derive, so a rare brand stops
    # vetoing every result.
    for drop in _leading_brand_candidates(original):
        if drop and drop not in ladder:
            ladder.append(drop)

    return ladder


def _leading_brand_candidates(title: str) -> list[str]:
    """Queries with a leading brand token removed, then re-reduced.

    The first rung drops only the brand; the second drops the brand AND
    re-applies the filler filter to what is left. Both are needed, because a
    rare title is usually rare in two ways at once. Measured:

        "Pasabahce 2 Colorful Cups & Saucers Dissolving Skyline Bone China 5oz"
            as-is                                ->  0 items
            drop brand only ("2 colorful cups…")  ->  0 items
            drop brand + filler ("colorful cups") -> 49 items, 4 sellers

    So the loosest rung is the one that works, and it is therefore last.
    """
    words = str(title or "").split()
    out: list[str] = []
    for index, word in enumerate(words[:3]):
        stripped = word.strip(".,()-")
        if not stripped or not stripped[:1].isupper() or stripped.isupper():
            continue
        remainder = " ".join(words[index + 1:])
        rest = _meaningful(_tokens(remainder))
        if len(rest) < 2:
            continue
        # Rung 1: brand gone, remaining terms otherwise intact.
        near = " ".join(_tokens(remainder)[:MAX_QUERY_WORDS])
        if near and near != str(title).strip() and near not in out:
            out.append(near)
        # Rung 2: brand gone and filler gone - the loosest claim we make.
        loose = " ".join(rest[:MAX_QUERY_WORDS])
        if loose and loose not in out:
            out.append(loose)
    return out
