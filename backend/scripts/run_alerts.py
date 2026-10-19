"""Run one alerts pass from the command line.

Alerts are not a timer inside the uvicorn process: that process only runs
while the backend is open by hand. This is the piece Task Scheduler can
call, so a tracked price that moved while nobody was looking still lands in
the inbox. See schedule_alerts.xml for the registration recipe.

Zero Browse calls and zero scraping: every comparison reads observations
this app already stored - tracker price checks and demand-monitor runs.
That is why this pass can run as often as you like; the quota concern
belongs to the runs that CREATE observations, not to the comparisons.

Idempotent: an alert is tied to the reading it describes, so running the
pass twice writes nothing the second time.

    python -m scripts.run_alerts

Exits non-zero only when the pass itself fails. Nothing new to compare is
not a failure - an empty inbox after an empty pass is the honest outcome.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from hunter.alerts import generate_alerts

    print("comparing stored observations (no Browse calls)")
    report = generate_alerts()

    written = 0
    for lane, label in (
        ("tracked_items", "tracked items"),
        ("monitored_queries", "monitored queries"),
    ):
        lane_report = report[lane]
        written += lane_report["written"]
        print(
            f"  {label}: {lane_report['products']} product(s) considered, "
            f"{lane_report['comparisons']} comparison(s), "
            f"{lane_report['written']} alert(s), "
            f"{lane_report['skipped']} already alerted"
        )
        for message in lane_report["messages"]:
            print(f"    - {message}")

    print(f"\nalerts={written}")
    if written == 0:
        print("nothing new to say - an empty pass is not a failure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
