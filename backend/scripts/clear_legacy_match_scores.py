"""Clear the fabricated match scores written before the C14 matcher existed.

`save_analysis_to_db` used to persist three hard-coded constants as if they
were measurements:

    supplier_type = "dropship",  confidence = "medium",  match_score = 0.5

So every supplier row saved between the start of the project and 2026-10-03
carries a 0.5 that no matcher ever produced. That is worse than a null: 0.5
sits in a 0..1 column looking like a real score, so any later aggregate over
`match_score` averages a measurement with a constant and quietly skews.

What this script does, and does not do:

  * NULLs `match_score` and `confidence` on those rows - the price, title, URL
    and delivery columns are untouched, because those were really read off the
    source and are the only copy.
  * Records nothing it cannot know. The score cannot be re-derived: it depends
    on which eBay product and supplier title were compared, and these rows do
    not record the query. Inventing a replacement would be the exact failure
    this cleanup exists to remove.
  * Refuses to touch any row whose pair is not the legacy one. Identity is
    `match_score = 0.5 AND confidence = 'medium'` - both hard-coded constants,
    so the pair cannot occur by accident. Post-2026-10-03 rows carry 'high',
    'low' or NULL, and a genuine future score of 0.5 would be 'high'/'low'.
    No timestamp comparison is involved, so re-running is harmless.

Usage (dry run first - it is the default):

    python -m scripts.clear_legacy_match_scores
    python -m scripts.clear_legacy_match_scores --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import SessionLocal  # noqa: E402
from db.models import SupplierMatch  # noqa: E402

# The exact pair the legacy code wrote. Both halves are constants, which is
# what makes this safe to select on.
LEGACY_SCORE = 0.5
LEGACY_CONFIDENCE = "medium"


def find_legacy(db):
    return (
        db.query(SupplierMatch)
        .filter(
            SupplierMatch.match_score == LEGACY_SCORE,
            SupplierMatch.confidence == LEGACY_CONFIDENCE,
        )
        .all()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it, this only reports what it would do.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        legacy = find_legacy(db)
        total = db.query(SupplierMatch).count()
        print(f"supplier_matches rows total : {total}")
        print(f"legacy (score={LEGACY_SCORE}, confidence={LEGACY_CONFIDENCE!r}) : {len(legacy)}")

        if not legacy:
            print("nothing to do - already clean")
            return 0

        print("\nthese rows would have match_score and confidence set to NULL:")
        for row in legacy[:10]:
            print(
                f"  id={row.id:<4} {str(row.supplier_name)[:26]:<26} "
                f"score={row.match_score} confidence={row.confidence} "
                f"price={row.supplier_price}"
            )
        if len(legacy) > 10:
            print(f"  ... and {len(legacy) - 10} more")

        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply to commit.")
            return 0

        for row in legacy:
            row.match_score = None
            row.confidence = None
        db.commit()

        remaining = len(find_legacy(db))
        print(f"\napplied. legacy rows remaining: {remaining}")
        if remaining:
            print("WARNING: some legacy rows were not cleared", file=sys.stderr)
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())