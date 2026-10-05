"""Run one demand-monitor pass from the command line.

A 7-day trend is a measurement of the GAPS between observations: two samples
an hour apart tell you nothing, two samples a week apart tell you something.
So the monitor has to run whether or not anyone is looking at the app - which
is why this is a script Task Scheduler can call, rather than something that
lives inside the uvicorn process (that only runs while you have the backend
open by hand).

Idempotent and cheap: one Browse call per alert-enabled tracked product. With
20 tracked products that is ~80 calls/day, against a 5,000/day allowance.

    python -m scripts.run_demand_monitor

Exits non-zero if every product failed, so Task Scheduler's "last run result"
actually tells you whether the job is healthy. Exits 0 when there was simply
nothing to sample - an empty watchlist is not a failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from db.database import SessionLocal
    from db.models import TrackedProduct
    from hunter.demand_monitor import fetch_and_record

    db = SessionLocal()
    try:
        products = (
            db.query(TrackedProduct)
            .filter(TrackedProduct.alert_enabled == True)  # noqa: E712
            .all()
        )
        names = [(p.product_name or "").strip() for p in products]
        names = [n for n in names if n]
    finally:
        db.close()

    if not names:
        print("nothing to sample: no alert-enabled tracked products")
        print("(add one on the Tracker page; a blank product name is skipped)")
        return 0

    print(f"sampling {len(names)} tracked product(s)")
    sampled = 0
    failed: list[str] = []

    for name in names:
        try:
            row = fetch_and_record(name, source="track_monitor")
        except Exception as e:  # noqa: BLE001 — one bad query must not stop the run
            print(f"  FAILED  {name[:52]}: {e}")
            failed.append(name)
            continue

        # A count of None means the request came back unusable - refused, or
        # nothing in band. That is recorded as no count rather than as 0, so it
        # cannot later read as a collapse in demand.
        if row.sold_30d is None:
            print(f"  no count {name[:52]} (recorded as unverified)")
        else:
            print(f"  {row.sold_30d:>5} sold  {name[:52]}")
            sampled += 1

    print(f"\nsampled={sampled} failed={len(failed)}")
    if sampled == 0 and failed:
        print("every product failed - check the eBay credentials in .env")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())