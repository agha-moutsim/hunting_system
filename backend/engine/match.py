"""Deterministic product matching — C14.

An eBay item and a supplier item are the same product only when THIS module
says so. Nothing else may decide: not the LLM, not a shared word in a
title, not a price that happens to fall in band.

    C14: "An eBay item and a supplier item are the same product only when a
    defined, code-level matcher scores them at or above threshold (title
    tokens + brand + key attributes + price plausibility; image phash when
    both images exist). Below threshold = unverified / 'no confirmed match' —
    shown as absent, not fudged. match_score is computed, never a constant;
    LLM confidence is display-only and never a substitute for the matcher."

Thresholds
    >= 0.65  verified     shown as a confirmed match
    >= 0.45  unverified   shown, labelled as not confirmed — never gates
    <  0.45  dropped      "no confirmed match"; the row is absent (C12)

Deliberately a near-leaf module: stdlib + numpy/PIL for pHash only, no
project imports, so every consumer (Deep Search, Analyze, Bulk, Hunter,
exports) scores identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "THRESHOLD_VERIFIED",
    "THRESHOLD_UNVERIFIED",
    "TIER_VERIFIED",
    "TIER_UNVERIFIED",
    "TIER_NO_MATCH",
    "MatchResult",
    "tokenize",
    "title_similarity",
    "brand_score",
    "attribute_score",
    "price_plausible",
    "phash_from_bytes",
    "phash_similarity",
    "compute_match",
    "passes_verified",
    "passes_threshold",
    "assign_match",
    "filter_matches",
    "score_candidates",
    "MATCH_METHOD",
]

# --- Thresholds (C14) ------------------------------------------------------

THRESHOLD_VERIFIED = 0.65
THRESHOLD_UNVERIFIED = 0.45

TIER_VERIFIED = "verified"
TIER_UNVERIFIED = "unverified"
TIER_NO_MATCH = "no_match"

# Human label for the below-threshold case — C14 fixes this wording.
NO_MATCH_LABEL = "no confirmed match"

# Recorded on every scored row so a reviewer can see which rule produced
# the number. The score itself is computed; this only names the method.
MATCH_METHOD = (
    "deterministic matcher v1: title tokens + brand + key attributes + "
    "price plausibility, blended with image phash when both images exist"
)


# --- Tokenisation ----------------------------------------------------------

# Words that carry no product identity. Deliberately small: dropping
# "for"/"with" helps, dropping "cordless" or "brushless" would destroy the
# signal this module exists to measure.
_STOPWORDS = frozenset(
    """
    a an the and or of to in on for with by from at as is are be this that
    it its into over under new free uk
    """.split()
)

# Split on anything that is not a letter, digit, or the common size/pack
# separators. Keeps "18v", "5l", "psb1800", "3-pack" intact as tokens.
_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Pack quantities, read off the RAW title rather than the token list:
# "3 pack" tokenises into two separate tokens ("3" and "pack", and the bare
# "3" is dropped for being one character), so a token-based matcher would
# never see the quantity — and would confirm a 3-pack eBay listing as the
# same product as a single-unit supplier row.
_QTY_RAW_RE = re.compile(
    r"\b(\d+)\s*(?:x\b|packs?\b|pcs\b|pieces\b|counts?\b|ct\b)"
    r"|\bx\s*(\d+)\b",
    re.IGNORECASE,
)


def tokenize(title: str) -> list[str]:
    """Lowercase, de-punctuated, stopword-free tokens, order preserved.

    Numbers are never dropped — model numbers, voltages and pack sizes are
    usually the only thing separating two look-alike products.
    """
    if not title:
        return []
    raw = _SPLIT_RE.sub(" ", str(title).lower()).split()
    return [t for t in raw if len(t) > 1 and t not in _STOPWORDS]


def _token_set(tokens: Iterable[str]) -> set[str]:
    return {t for t in tokens if t}


# --- Signal 1: title tokens ------------------------------------------------

def title_similarity(ebay_title: str, candidate_title: str) -> float:
    """Dice coefficient over token sets — 2|A∩B| / (|A|+|B|).

    Chosen over plain Jaccard because a supplier title is routinely shorter
    than the eBay title ("Drill" vs "Bosch PSB 1800 LI-2 Cordless Combi
    Drill 18V"); Dice stays honest about a genuinely partial overlap without
    punishing a concise-but-correct listing the way raw Jaccard does.

    Identical token sets -> 1.0. No shared token -> 0.0 (and that alone
    puts the pair far below any threshold).
    """
    a = _token_set(tokenize(ebay_title))
    b = _token_set(tokenize(candidate_title))
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if overlap == 0:
        return 0.0
    return (2.0 * overlap) / (len(a) + len(b))


# --- Signal 2: brand -------------------------------------------------------

def brand_score(brand: str, candidate_title: str) -> float:
    """1.0 when the eBay side's brand appears in the candidate, else 0.0.

    No brand supplied -> 1.0 by neutral scoring (not 0.0): absence of a
    brand is missing evidence, not contradictory evidence, and must not drag
    an otherwise identical product below threshold.

    A brand known to be MISMATCHED is handled by the caller as a veto —
    this function only reports presence.
    """
    if not brand:
        return 1.0
    brand_tokens = _token_set(tokenize(brand))
    if not brand_tokens:
        return 1.0
    cand = _token_set(tokenize(candidate_title))
    return 1.0 if brand_tokens <= cand else 0.0


# --- Signal 3: key attributes ---------------------------------------------

# Tokens that identify a specific SKU rather than a product family.
# A model is only discriminating when it is not just "18v" or "500g".
_MEASURE_RE = re.compile(r"^(\d+(\.\d+)?)(v|w|a|ah|mm|cm|kg|g|l|ml|inch|in|ft|m|hz|db|mph|bar|psi|kw|hp|pcs|pack|x)$")

# Colours, sizes and pack quantities are the classic false-match axes:
# a black case and a grey case, 3 m and 5 m, a single unit and a 10-pack.
_COLOR_WORDS = frozenset(
    """
    black white grey gray red blue green yellow orange purple pink brown
    silver gold beige navy teal olive khaki multicolour multicolor
    """.split()
)
_SIZE_WORDS = frozenset(
    "xs s m l xl xxl 2xl 3xl petite slim regular long short".split()
)


def _models(raw_title: str, tokens: set[str]) -> set[str]:
    """Discriminating model tokens: alphanumeric with a digit, not a measurement.

    Model numbers frequently arrive split by a separator — "PSB 1800",
    "GSB 18V-50" — where neither half is a model on its own. So alongside
    the joined tokens we also merge an adjacent alpha-prefix of 2-4 chars
    with the run that follows it: `psb` + `1800` -> `psb1800`.

    The prefix length cap matters. Without it `dewalt` + `dcd778` would
    merge into a spurious `dewaltdcd778` that matches nothing, turning a
    genuine match into a veto. The unmerged token (`dcd778`) is kept in the
    set too, so both sides of a real match still intersect.

    A head may also qualify when it already contains a digit — `wh1000` +
    `xm4` is one model written with a space, and refusing to merge it made
    "WH1000 XM4" veto against "WH1000XM4" as though they were different
    headphones. The alpha-only path keeps its 2-4 char cap; the alnum path
    needs none because a head with a digit is already a part-number, not a
    word like `dewalt`.
    """
    out: set[str] = set()
    for t in tokens:
        if _MEASURE_RE.match(t) or t.isdigit() or t.isalpha():
            continue
        if any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
            out.add(t)

    words = tokenize(raw_title)
    for i in range(len(words) - 1):
        head, tail = words[i], words[i + 1]
        head_ok = (head.isalpha() and 2 <= len(head) <= 4) or any(
            c.isdigit() for c in head
        )
        if not head_ok or not any(c.isdigit() for c in tail):
            continue
        if len(tail) >= 2 and (tail.isalnum() or tail.isdigit()):
            out.add(head + tail)
    return out


def _quantities(raw_title: str) -> set[int]:
    """Pack quantities asserted in a title: '3 pack', '12pack', '4x', 'x4'.

    Takes the RAW title, not tokens — see `_QTY_RAW_RE` for why.
    """
    if not raw_title:
        return set()
    out: set[int] = set()
    for m in _QTY_RAW_RE.finditer(str(raw_title)):
        n = m.group(1) or m.group(2)
        if n:
            out.add(int(n))
    return out


def _colours(tokens: set[str]) -> set[str]:
    """Colour words, with grey/gray folded to one spelling."""
    return {"gray" if t == "grey" else t for t in tokens & _COLOR_WORDS}


def attribute_score(ebay_title: str, candidate_title: str) -> float:
    """Fraction of the eBay side's key attributes preserved in the candidate.

    Attributes considered: model numbers, colour, size, pack quantity.
    Missing evidence scores neutrally (1.0) so an attribute-poor title is
    not penalised — only a *conflicting* attribute costs score, and the
    hard conflicts are applied as vetoes by `compute_match`.
    """
    a_tokens = _token_set(tokenize(ebay_title))
    b_tokens = _token_set(tokenize(candidate_title))
    if not a_tokens:
        return 1.0

    checks: list[bool] = []

    models = _models(ebay_title, a_tokens)
    if models:
        checks.append(bool(models & _models(candidate_title, b_tokens)))

    colours = _colours(a_tokens)
    if colours:
        checks.append(bool(colours & _colours(b_tokens)))

    sizes = a_tokens & _SIZE_WORDS
    if sizes:
        checks.append(bool(sizes & b_tokens))

    quantities = _quantities(ebay_title)
    if quantities:
        checks.append(bool(quantities & _quantities(candidate_title)))

    if not checks:
        return 1.0
    return sum(checks) / len(checks)


# --- Signal 4: price plausibility ------------------------------------------

def _price_ratio(ebay_price: Any, supplier_price: Any) -> float | None:
    """supplier / ebay, or None when either side is absent or unparseable.

    None means "we do not know", which both `price_plausible` and the price
    veto read as no evidence — never as a pass.
    """
    try:
        e = float(ebay_price)
        s = float(supplier_price)
    except (TypeError, ValueError):
        return None
    if e <= 0 or s <= 0:
        return None
    return s / e


def price_plausible(ebay_price: float, supplier_price: float) -> float:
    """How sane a supplier price is *as a resale source price*.

    You buy at the supplier price and sell on eBay, so a sane ratio is
    roughly 0.2-1.0. A supplier charging more than eBay is not a source at
    all; a supplier at 1% of eBay is almost certainly a different or
    misrepresented item. Both should cost score.

    Returns 0.0 rather than raising when either price is missing — an
    unknown price can neither confirm nor deny a match, and returning 1.0
    here would let a price-less row sail past threshold.
    """
    try:
        e = float(ebay_price)
        s = float(supplier_price)
    except (TypeError, ValueError):
        return 0.0
    if e <= 0 or s <= 0:
        return 0.0

    ratio = s / e

    # Perfectly placed: buy at 20%-100% of the sell price.
    if 0.20 <= ratio <= 1.00:
        return 1.0

    if ratio < 0.20:
        # Linear fall to zero by 5% — implausibly cheap.
        return max(0.0, ratio / 0.20) if ratio > 0 else 0.0

    # ratio > 1.00: lose score steadily, zero by 1.6x (no margin possible).
    return max(0.0, 1.0 - (ratio - 1.00) / 0.60)


# --- Signal 5: image pHash --------------------------------------------------

def phash_from_bytes(data: bytes) -> int | None:
    """63-bit perceptual hash of an image, or None if it cannot be read.

    Standard pHash: greyscale -> 32x32 -> DCT-II -> top-left 8x8 (DC
    dropped) -> bit per coefficient above its own median.

    Returns None on any failure (bad bytes, truncated download). A missing
    hash is *unknown*, and the caller must fall back to text-only scoring
    rather than treating two unknowns as a match.
    """
    if not data:
        return None
    try:
        import io

        import numpy as np
        from PIL import Image, ImageOps
    except Exception:  # pragma: no cover - optional deps
        return None

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.grayscale(img).resize((32, 32), Image.LANCZOS)
        block = np.asarray(img, dtype=np.float64)
    except Exception:
        return None

    try:
        # DCT-II as a matrix product: T @ X @ T.T, N = 32.
        n = block.shape[0]
        i = np.arange(n)
        j = np.arange(n)
        T = np.cos(np.pi * (2 * j + 1)[None, :] * i[:, None] / (2 * n))
        dct = T @ block @ T.T
    except Exception:
        return None

    low = dct[:8, :8].flatten()
    if low.size < 2:
        return None
    median = float(np.median(low[1:]))  # skip the DC term
    bits = low[1:] > median
    if bits.size != 63:
        return None

    value = 0
    for b in bits:
        value = (value << 1) | (1 if b else 0)
    return value


def phash_similarity(hash_a: int | None, hash_b: int | None) -> float | None:
    """1.0 identical .. 0.0 unrelated; None when either hash is unknown.

    The 63 bits are compared by Hamming distance, mapped linearly: distance
    0 -> 1.0, distance >= 32 -> 0.0. Published pHash practice treats a
    distance under ~10 as the same image; 32 is the point at which the two
    hashes are no better than unrelated.
    """
    if hash_a is None or hash_b is None:
        return None
    distance = bin(int(hash_a) ^ int(hash_b)).count("1")
    return max(0.0, 1.0 - (distance / 32.0))


# --- Assembly ---------------------------------------------------------------

# Text-only weights (sum 1.0). Title dominates: it is the one signal every
# pair actually has.
_W_TITLE = 0.45
_W_BRAND = 0.15
_W_ATTR = 0.20
_W_PRICE = 0.20

# Added when both images hash successfully; every weight is then divided by
# the new total, so the text signals keep their relative influence.
_W_PHASH = 0.25

# Hard vetoes cap the score (they do not zero it, so the reason stays
# legible in `components`) — a vetoed pair can never reach 0.45.
_VETO_CAP_MODEL = 0.30
_VETO_CAP_PRICE = 0.35
_VETO_CAP_NO_OVERLAP = 0.30


@dataclass(frozen=True)
class MatchResult:
    """The outcome of scoring one candidate against one eBay title."""

    score: float
    tier: str
    provenance: str
    provenance_label: str
    method: str
    reason: str
    components: dict[str, float] = field(default_factory=dict)
    vetoed_by: str = ""

    @property
    def is_match(self) -> bool:
        """True only at the verified threshold (C14's confirmed match)."""
        return self.tier == TIER_VERIFIED

    @property
    def label(self) -> str:
        """Display label — 'no confirmed match' below threshold (C14)."""
        if self.tier == TIER_VERIFIED:
            return "verified match"
        if self.tier == TIER_UNVERIFIED:
            return "not confirmed"
        return NO_MATCH_LABEL

    @property
    def dropped(self) -> bool:
        return self.tier == TIER_NO_MATCH


def _tier_for(score: float) -> str:
    if score >= THRESHOLD_VERIFIED:
        return TIER_VERIFIED
    if score >= THRESHOLD_UNVERIFIED:
        return TIER_UNVERIFIED
    return TIER_NO_MATCH


def compute_match(
    ebay_title: str,
    candidate_title: str,
    *,
    brand: str = "",
    ebay_price: float = 0.0,
    candidate_price: float = 0.0,
    ebay_image_hash: int | None = None,
    candidate_image_hash: int | None = None,
) -> MatchResult:
    """Score one candidate. The only entry point that may set `match_score`.

    Every component is computed here; nothing is passed in pre-scored, and
    no caller may supply a score. Hard conflicts (a different model number)
    cap the result below the unverified floor so a vetoed pair is reported
    as "no confirmed match" rather than merely weak.
    """
    title = title_similarity(ebay_title, candidate_title)
    brand_v = brand_score(brand, candidate_title)
    attrs = attribute_score(ebay_title, candidate_title)
    price = price_plausible(ebay_price, candidate_price)
    phash = phash_similarity(ebay_image_hash, candidate_image_hash)

    components: dict[str, float] = {
        "title": round(title, 4),
        "brand": round(brand_v, 4),
        "attributes": round(attrs, 4),
        "price": round(price, 4),
    }

    weights = {
        "title": _W_TITLE,
        "brand": _W_BRAND,
        "attributes": _W_ATTR,
        "price": _W_PRICE,
    }
    if phash is not None:
        components["phash"] = round(phash, 4)
        weights["phash"] = _W_PHASH

    total_weight = sum(weights.values())
    score = sum(components[k] * w for k, w in weights.items()) / total_weight

    vetoed_by = ""

    a = _token_set(tokenize(ebay_title))
    b = _token_set(tokenize(candidate_title))

    # --- Hard veto 1: conflicting model numbers.
    # Two products whose only shared words are "drill" and "18v", but whose
    # model tokens ("psb1800" vs "gsb18") are disjoint and non-overlapping,
    # are different products however similar the prose sounds. C14 exists
    # for exactly this case.
    models_a = _models(ebay_title, a)
    models_b = _models(candidate_title, b)
    if models_a and models_b and not (models_a & models_b):
        score = min(score, _VETO_CAP_MODEL)
        vetoed_by = "conflicting model number"

    # --- Hard veto 2: price makes the pair impossible as a resale source.
    # Only when we actually have both prices; unknown or unparseable prices
    # must not veto (and must not raise — `price_plausible` already treats
    # them as "no evidence", so the veto does the same).
    if vetoed_by == "":
        ratio = _price_ratio(ebay_price, candidate_price)
        if ratio is not None and (ratio > 1.60 or ratio < 0.05):
            score = min(score, _VETO_CAP_PRICE)
            vetoed_by = "price makes this pair implausible"

    # --- Hard veto 3: brand explicitly present but different.
    if vetoed_by == "" and brand:
        brand_tokens = _token_set(tokenize(brand))
        if brand_tokens and b and not (brand_tokens & b):
            score = min(score, _VETO_CAP_MODEL)
            vetoed_by = "brand mismatch"

    # --- Hard veto 0: no shared title tokens at all.
    # Applied LAST because it is the least specific reason — when a model
    # number or a brand already explains the failure, that is the more
    # useful thing to report. Its real job is the case where nothing else
    # fires: brand, attributes and price all score neutrally when there is
    # nothing to contradict them, so a completely unrelated title would
    # otherwise collect 0.55 and clear the 0.45 floor on the ABSENCE of
    # evidence. Zero overlap is not weak evidence of a relationship — it is
    # no evidence of one, and C12 admits a row only past threshold.
    if title <= 0.0:
        score = min(score, _VETO_CAP_NO_OVERLAP)
        vetoed_by = vetoed_by or "no shared title tokens"

    # --- Hard veto 2: price makes the pair impossible as a resale source.
    # Only when we actually have both prices; unknown or unparseable prices
    # must not veto (and must not raise — `price_plausible` already treats
    # them as "no evidence", so the veto does the same).
    if vetoed_by == "":
        ratio = _price_ratio(ebay_price, candidate_price)
        if ratio is not None and (ratio > 1.60 or ratio < 0.05):
            score = min(score, _VETO_CAP_PRICE)
            vetoed_by = "price makes this pair implausible"

    # --- Hard veto 3: brand explicitly present but different.
    if vetoed_by == "" and brand:
        brand_tokens = _token_set(tokenize(brand))
        cand_tokens = _token_set(tokenize(candidate_title))
        if brand_tokens and cand_tokens and not (brand_tokens & cand_tokens):
            score = min(score, _VETO_CAP_MODEL)
            vetoed_by = "brand mismatch"

    # Round ONCE, before tiering. The per-signal components are rounded for
    # display, so their weighted sum lands at e.g. 0.44999 — tiering that
    # unrounded value while SHOWING 0.45 would mean a row could display a
    # passing score and still be dropped. Whatever we print is what we
    # judge by.
    score = round(max(0.0, min(1.0, score)), 4)
    tier = _tier_for(score)

    # Provenance tier follows the score — never "verified" on a guess (C13).
    provenance = "verified" if tier == TIER_VERIFIED else "unverified"

    reason = (
        f"score {score:.3f} >= {THRESHOLD_VERIFIED} — confirmed"
        if tier == TIER_VERIFIED
        else f"score {score:.3f} < {THRESHOLD_VERIFIED} — {NO_MATCH_LABEL}"
        if tier == TIER_NO_MATCH
        else f"score {score:.3f} between {THRESHOLD_UNVERIFIED} and "
        f"{THRESHOLD_VERIFIED} — shown, never confirmed"
    )
    if vetoed_by:
        reason = f"{vetoed_by}; {reason}"

    return MatchResult(
        score=round(score, 4),
        tier=tier,
        provenance=provenance,
        provenance_label="Verified" if provenance == "verified" else "Unverified",
        method=MATCH_METHOD,
        reason=reason,
        components=components,
        vetoed_by=vetoed_by,
    )


# --- Helpers for consumers ---------------------------------------------------


def passes_verified(score: float) -> bool:
    return score >= THRESHOLD_VERIFIED


def passes_threshold(score: float) -> bool:
    """Above the unverified floor — shown, but not confirmed."""
    return score >= THRESHOLD_UNVERIFIED


def assign_match(row: dict, result: MatchResult) -> dict:
    """Write the computed match onto a supplier row (never the reverse).

    Overwrites any pre-existing `match_score`: the LLM's confidence is
    display-only per C14 and must never be what lands in this field.
    """
    if not isinstance(row, dict):
        return row
    row["match_score"] = result.score
    row["match_tier"] = result.tier
    row["match_label"] = result.label
    row["match_provenance"] = result.provenance
    row["match_provenance_label"] = result.provenance_label
    row["match_basis"] = result.reason
    row["match_method"] = result.method
    row["match_components"] = dict(result.components)
    if result.vetoed_by:
        row["match_veto"] = result.vetoed_by
    return row


def filter_matches(rows: list, threshold: float = THRESHOLD_UNVERIFIED) -> list:
    """Keep rows at or above `threshold`, preserving order (C12).

    Rows without a computed `match_score` are **dropped**: an unscanned row
    has no evidence either way, and C12 says a supplier row appears only
    when it passed the threshold.
    """
    kept = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("match_score"))
        except (TypeError, ValueError):
            continue
        if score >= threshold:
            kept.append(row)
    return kept


def score_candidates(
    ebay_title: str,
    candidates: Iterable[dict],
    *,
    brand: str = "",
    ebay_price: float = 0.0,
    ebay_image_hash: int | None = None,
) -> list[dict]:
    """Score every candidate, sort by score desc, tag each with its tier.

    Cheap and side-effecting only on the rows it is given — usable directly
    by Deep Search, Analyze, Bulk and Hunter without each re-implementing
    the ordering.
    """
    scored: list[dict] = []
    for row in candidates or []:
        if not isinstance(row, dict):
            continue
        result = compute_match(
            ebay_title,
            str(row.get("product_title") or row.get("title") or ""),
            brand=brand,
            ebay_price=ebay_price,
            candidate_price=row.get("price") or 0.0,
            ebay_image_hash=ebay_image_hash,
            candidate_image_hash=row.get("image_hash"),
        )
        scored.append(assign_match(row, result))

    scored.sort(key=lambda r: r.get("match_score", 0.0), reverse=True)
    return scored
