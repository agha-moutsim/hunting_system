"""Run one deals-board refresh from the command line.

Why this is a script Task Scheduler calls, rather than something that happens
when the page is opened:

Pricing the cards is one eBay Browse call EACH — about 73 of them. Waiting on
that inside a request would time out, and doing it per page view would spend
the whole 5,000/day allowance in under an hour of one tab being left open. So
the fetch runs on a schedule and the API only ever reads what this stored.

At the default hourly cadence that is ~108 calls x 24 = ~2,600/day (108 is the
measured cost of a full page), which leaves room for everything else the app
does.

    python -m scripts.run_deals_refresh              # full refresh, ~73 calls
    python -m scripts.run_deals_refresh --limit 10   # cheap partial run

Partial runs still store every card the page shows; `--limit` only decides how
many of them get a price this time. That is deliberate: the cards are real
either way, and an unpriced card is shown as "see price on eBay" rather than
being hidden.

Exits non-zero when the deals page itself could not be read, so Task
Scheduler's "last run result" means something. A run that stored cards but read
no prices is NOT a failure and exits 0 — the listings are real, they simply
carry no price, and the board says so.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="price only the first N cards (0 = all; cards are stored either way)",
    )
    args = parser.parse_args()

    from hunter import deals

    try:
        result = deals.refresh(limit=args.limit or None)
    except Exception as exc:  # noqa: BLE001 - the exit code is the report
        print(f"FAILED to read eBay's deals page: {exc}")
        print("nothing was stored; the previous pool is untouched")
        return 1

    print(f"stored {result['total']} cards from {result['source_label']}")
    print(f"  added={result['added']} updated={result['updated']} "
          f"removed={result['removed']}")
    print(f"  prices read: {result['priced']}/{result['cards']} "
          f"({result['api_calls']} Browse calls, "
          f"{result['price_failures']} failed)")

    unpriced = result["cards"] - result["priced"]
    if unpriced:
        # Not a failure. Said plainly so it is not mistaken for one.
        print(f"  {unpriced} card(s) carry no price this round - they are still "
              f"real listings and the board shows 'see price on eBay' for them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
