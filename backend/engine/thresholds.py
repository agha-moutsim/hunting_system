"""C14 threshold feedback - replay stored match scores, change nothing.

Phase I asks a narrow question: if the confirmed / shown thresholds were
different, which of the supplier rows ALREADY STORED would have moved? This
module answers exactly that and returns the differences. It does not choose a
threshold, write a setting, or re-run the matcher.

The important limit is structural. `analysis_pipeline` never stores a row the
matcher put below the shown threshold, so those rows do not exist in
`supplier_matches`. A LOWER threshold therefore cannot be replayed against
outcomes this app never recorded. A higher threshold can show what would have
been lost, and a lower one can only show stored rows that would have been
promoted from "not confirmed" to "confirmed". The response says this in words
so a reader is never handed a one-sided table as if it were the whole story.

Every count is a count of stored supplier rows. One product can contribute
several rows; `products` is reported beside `scored_rows` for that reason.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

from engine.match import (
    THRESHOLD_UNVERIFIED,
    THRESHOLD_VERIFIED,
    TIER_NO_MATCH,
    TIER_UNVERIFIED,
    TIER_VERIFIED,
)

__all__ = ["replay_thresholds", "tier_for", "TIER_LABELS"]

TIER_LABELS = {
    TIER_VERIFIED: "confirmed match",
    TIER_UNVERIFIED: "not confirmed",
    TIER_NO_MATCH: "no confirmed match",
}

_VERDICTS = ("pass", "fail", "pending", "not_recorded")
_DEFAULT_SWEEP = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)


def tier_for(score: float, verified: float, unverified: float) -> str:
    """The C14 tier a score falls into under a given pair of thresholds."""
    if score >= verified:
        return TIER_VERIFIED
    if score >= unverified:
        return TIER_UNVERIFIED
    return TIER_NO_MATCH


def _valid_score(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or score < 0.0 or score > 1.0:
        return None
    return score


def _verdict(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in ("pass", "fail", "pending") else "not_recorded"


def _threshold(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number between 0 and 1.")
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be a number between 0 and 1.")
    return number


def _tier_counts(rows: list[dict], verified: float, unverified: float) -> dict:
    counts = {TIER_VERIFIED: 0, TIER_UNVERIFIED: 0, TIER_NO_MATCH: 0}
    for row in rows:
        counts[tier_for(row["score"], verified, unverified)] += 1
    return counts


def _outcomes(rows: list[dict], verified: float, unverified: float) -> dict:
    """How many CONFIRMED rows sit on each stored product verdict."""
    counts = {key: 0 for key in _VERDICTS}
    for row in rows:
        if tier_for(row["score"], verified, unverified) == TIER_VERIFIED:
            counts[row["verdict"]] += 1
    return counts


def _sweep(rows: list[dict], current_verified: float, current_unverified: float) -> list[dict]:
    thresholds = sorted(set(_DEFAULT_SWEEP) | {round(current_verified, 4)})
    out = []
    for threshold in thresholds:
        confirmed = [
            row
            for row in rows
            if row["score"] >= threshold
        ]
        outcomes = {key: 0 for key in _VERDICTS}
        for row in confirmed:
            outcomes[row["verdict"]] += 1
        out.append(
            {
                "verified_threshold": threshold,
                "unverified_threshold": current_unverified,
                "confirmed": len(confirmed),
                "confirmed_lost_vs_current": sum(
                    1
                    for row in rows
                    if row["score"] >= current_verified
                    and row["score"] < threshold
                ),
                "confirmed_gained_vs_current": sum(
                    1
                    for row in rows
                    if row["score"] < current_verified
                    and row["score"] >= threshold
                ),
                "confirmed_pass": outcomes["pass"],
                "confirmed_fail": outcomes["fail"],
                "confirmed_pending": outcomes["pending"],
                "confirmed_not_recorded": outcomes["not_recorded"],
            }
        )
    return out


def replay_thresholds(
    rows: Iterable[Mapping],
    *,
    current_verified: float = THRESHOLD_VERIFIED,
    current_unverified: float = THRESHOLD_UNVERIFIED,
    proposed_verified: float | None = None,
    proposed_unverified: float | None = None,
    difference_limit: int = 100,
) -> dict:
    """Report which stored match rows would change tier.

    `rows` are mappings with `match_score` and, when available, `product_id`,
    `product_title`, `supplier_name`, `supplier_title` and `verdict`. A row is
    still counted in `stored_rows` when its score is missing or unusable; it is
    then excluded from every tier count and reported as `unscored_rows`.
    """
    current_verified = _threshold(current_verified, "current_verified")
    current_unverified = _threshold(current_unverified, "current_unverified")
    if current_unverified > current_verified:
        raise ValueError(
            "The shown threshold cannot be higher than the confirmed threshold."
        )

    proposed_verified = (
        current_verified
        if proposed_verified is None
        else _threshold(proposed_verified, "proposed_verified")
    )
    proposed_unverified = (
        current_unverified
        if proposed_unverified is None
        else _threshold(proposed_unverified, "proposed_unverified")
    )
    if proposed_unverified > proposed_verified:
        raise ValueError(
            "The shown threshold cannot be higher than the confirmed threshold."
        )

    stored = list(rows)
    scored: list[dict] = []
    unscored = 0
    for row in stored:
        score = _valid_score(row.get("match_score"))
        if score is None:
            unscored += 1
            continue
        scored.append(
            {
                "score": score,
                "product_id": row.get("product_id"),
                "product_title": row.get("product_title"),
                "supplier_name": row.get("supplier_name"),
                "supplier_title": row.get("supplier_title"),
                "verdict": _verdict(row.get("verdict")),
            }
        )

    current_tiers = _tier_counts(scored, current_verified, current_unverified)
    proposed_tiers = _tier_counts(scored, proposed_verified, proposed_unverified)

    difference_rows: list[dict] = []
    counts = {
        "changed": 0,
        "confirmed_lost": 0,
        "confirmed_gained": 0,
        "shown_lost": 0,
        "shown_gained": 0,
        "verified_to_unverified": 0,
        "verified_to_no_match": 0,
        "unverified_to_verified": 0,
        "unverified_to_no_match": 0,
        "no_match_to_verified": 0,
        "no_match_to_unverified": 0,
    }
    for row in scored:
        before = tier_for(row["score"], current_verified, current_unverified)
        after = tier_for(row["score"], proposed_verified, proposed_unverified)
        if before == after:
            continue

        key = f"{before}_to_{after}"
        if before == TIER_VERIFIED and after != TIER_VERIFIED:
            counts["confirmed_lost"] += 1
        if before != TIER_VERIFIED and after == TIER_VERIFIED:
            counts["confirmed_gained"] += 1
        if before != TIER_NO_MATCH and after == TIER_NO_MATCH:
            counts["shown_lost"] += 1
        if before == TIER_NO_MATCH and after != TIER_NO_MATCH:
            counts["shown_gained"] += 1
        if key in counts:
            counts[key] += 1
        counts["changed"] += 1

        difference_rows.append(
            {
                "product_id": row["product_id"],
                "product_title": row["product_title"],
                "supplier_name": row["supplier_name"],
                "supplier_title": row["supplier_title"],
                "verdict": row["verdict"],
                "match_score": round(row["score"], 4),
                "current_tier": before,
                "proposed_tier": after,
                "change": key,
            }
        )

    difference_rows.sort(
        key=lambda row: (row["change"], -row["match_score"], row["product_title"] or "")
    )
    truncated = len(difference_rows) > difference_limit
    difference_rows = difference_rows[:difference_limit]

    products = {
        row["product_id"]
        for row in scored
        if row["product_id"] is not None
    }

    return {
        "current": {
            "verified": current_verified,
            "unverified": current_unverified,
        },
        "proposed": {
            "verified": proposed_verified,
            "unverified": proposed_unverified,
        },
        "sample": {
            "stored_rows": len(stored),
            "scored_rows": len(scored),
            "unscored_rows": unscored,
            "products": len(products),
            "rows_with_a_verdict": sum(
                1 for row in scored if row["verdict"] != "not_recorded"
            ),
        },
        "current_tiers": current_tiers,
        "proposed_tiers": proposed_tiers,
        "outcomes": {
            "current_confirmed_by_verdict": _outcomes(
                scored, current_verified, current_unverified
            ),
            "proposed_confirmed_by_verdict": _outcomes(
                scored, proposed_verified, proposed_unverified
            ),
        },
        "differences": {
            **counts,
            "rows": difference_rows,
            "truncated": truncated,
        },
        "sweep": _sweep(scored, current_verified, current_unverified),
        "changes_applied": False,
        "note": (
            "Read-only replay. No threshold was changed; the C14 constants "
            "still decide every match."
        ),
        "limitation": (
            "Supplier rows the matcher dropped were never stored, so a lower "
            "threshold's newly admitted rows cannot be replayed. Only rows "
            "already in supplier_matches appear here."
        ),
    }
