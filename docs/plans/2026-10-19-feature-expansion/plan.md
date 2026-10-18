# Plan

The ten new features, sequenced. One phase per commit. Each phase is independently shippable.

---

## 1. Sequence at a glance

| Phase | Feature                       | Size | Depends on       | Browse cost                             |
| ----- | ----------------------------- | ---- | ---------------- | --------------------------------------- |
| A     | Passive capture               | M    | -                | 0 (the user's own session)              |
| B     | Rich field persistence        | M    | -                | 0 (fields already received)             |
| C     | Verified-first + Sources      | M    | A, B             | 0 (read-only)                           |
| D     | Fee and break-even calculator | M    | -                | 0 (pure arithmetic)                     |
| E     | Alerts                        | M    | B                | 0 for alerts; saved searches cost quota |
| F     | Title helper                  | S    | -                | Uses listings already fetched           |
| G     | Listing age and churn         | S    | B + elapsed time | 0 (reads observations)                  |
| H     | Seller footprint              | S    | B                | 0 (reads observations)                  |
| I     | Own-sales P&L + feedback      | M    | -                | 0                                       |
| J     | Marketplace expansion         | M    | D                | Existing calls, new marketplace         |

Total: 3 S, 7 M. No L phases.

---

## 2. Why this order

**A and B come first, and this is the only ordering decision that really matters.**

Both are pure _collection_, and everything downstream is a _reader_ of what they store.

- G cannot exist on day one no matter when it is built - "listed 74 days ago" and "delisted since
  October" need history that only starts accumulating once B ships. Every week B is delayed is a
  week added to the date G becomes useful.
- H is arithmetic over observations. No observations, no seller page.
- E's price history improves with every observation recorded.

So A and B are not first because they are most visible. They are first because **they are the only
phases whose value increases with time**, and time is the one input that cannot be bought.

**C follows immediately** because it fixes a live presentation problem: 39 stored rows currently
carry live-listing evidence under sold labels, and the tool has no way to show a user which rows
are which. C is the presentation-level answer, and it is what makes A's data visibly valuable
rather than a table nobody reads.

**D, E and F are self-contained** and could be built at any time. They are placed next because they
deliver value with no waiting: fees are arithmetic, alerts read what is already stored, titles read
listings already fetched.

**G and H are deliberately late.** Building them earlier produces empty screens and a temptation
to fill them with something invented. Late is also when they are worth most.

**I is the loop** and depends only on the user recording sales, so it can be pulled forward if
desired - it is placed here because it benefits from the observation history that A and B create.

**J is last** because it multiplies everything above it. Adding markets before the UK behaviour is
honest would multiply the mistakes.

---

## 3. Milestones

```
M1  COLLECTION LIVE      A + B     the dataset starts growing; the clock starts
M2  TRUST                C         verified-first and Sources; the differentiator ships
M3  QUICK WINS           D + E + F arithmetic, alerts, titles - no waiting on data
M4  ANALYTICS            G + H     age, churn, sellers - now that history exists
M5  THE LOOP             I         real P&L, threshold replay
M6  REACH                J         more marketplaces
```

M1 is the milestone that matters. If only A and B ever ship, the project is still better off than
it was, because it would be accumulating data it currently throws away.

---

## 4. Parallel / independent work

Phases D, F and I have no dependency on collection and can be interleaved whenever a confidence
boost is useful, or whenever a phase is blocked. D and F in particular are self-contained and
fully testable offline.

Phase B is the highest-leverage change per line of code in the whole plan: it makes zero extra
API calls and unlocks G, H and postage-in-margin. If only one thing is built, build B.

---

## 5. Risks and mitigations

| Risk                                                                                   | Mitigation                                                                                                             |
| -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Passive capture is judged abusive and the eBay account is banned                       | Hard caps in code (one capture per item per 6h, max 60/hour), no navigation, quiet mode. See constraints section 4.    |
| SerpApi is 0/250 until 2026-11-08, so the Analyze pipeline cannot be driven end to end | A, B, D, F and I are testable offline. Do not gate the plan on live supplier discovery.                                |
| Adding rows to `purchase_captures` breaks the existing upsert read path                | Change to append plus latest-per-item read in one commit, with a migration test and a test for the read path.          |
| `item_creation_date` is absent for some listings                                       | Nullable, rendered as "not measured". Never defaulted to today, which would fabricate a brand-new listing.             |
| Fee tables change                                                                      | Version the table, state the version in the response, and warn when it is stale.                                       |
| Alert noise                                                                            | Alerts require two real comparands. No comparand, no alert.                                                            |
| Quota exhaustion from saved searches                                                   | Ship alerts first at zero Browse cost; enable saved-search runs only with a stated budget under the 5,000/day ceiling. |
| The deals board must not regress                                                       | Its cadence and size are frozen by decision: 73 items, hourly. Do not touch it while adding phases.                    |
| Scope creep into the rest of the product                                               | Every phase lists the files it may touch. Anything else is a separate decision.                                        |

---

## 6. Deliberately excluded

Recorded so they are not re-litigated:

- Sold counts, units sold, revenue estimates, sell-through, search volume - **measured
  unavailable**, and inventing them is the one thing this project has consistently refused to do.
- ZIK's Shopify suite (AdSpy, Sales Tracker, Store Finder) - off-niche.
- Autopilot and listing integrations - eBay's Sell API, different product, ToS exposure.
- Reaching the 6,038 deals behind eBay's AJAX call - measured unreachable; 192 is the ceiling.
- A crawler over item ids using the logged-in account - account-ban risk, and it would destroy the
  data source the whole plan depends on.

---

## 7. Next action

Switch out of plan mode, then start **Phase A: passive capture**.

Order of work inside Phase A:

1. `extension/manifest.json` - add content scripts, `webNavigation`, keep `storage` and `activeTab`.
2. `extension/content.js` - item-id detection and the `item-seen` message.
3. `extension/background.js` - dedupe window, hourly cap, daily counter, badge, quiet mode.
4. `extension/popup.*` - today's count, last capture, backend reachability, quiet toggle.
5. `backend/api/extension.py` - add `GET /extension/status`.
6. `tests/test_extension_api.py` - offline coverage.
7. Full suite, production build, one commit, push.

Then **Phase B**, without waiting: the two together are M1, and M1 is when the clock starts.
