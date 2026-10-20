"use client";

import Badge from "@/components/ui/Badge";
import {
  NO_LONGER_LISTED_LABEL,
  firstSeenChipLabel,
  firstSeenLabel,
  lastSeenLabel,
  listingAgeLabel,
} from "@/lib/churn";
import type { ListingAgeInfo } from "@/lib/types";

/**
 * The compact age/status chip.
 *
 * Three distinct states, never merged:
 *
 *  - a real age from eBay's creation date    → "LISTED 74 DAYS AGO"
 *  - no creation date, but this app saw it   → "FIRST SEEN 12 OCT 2026"
 *  - missing from the latest search sample   → "NO LONGER LISTED"
 *
 * The second state is not an age. It says what it is, and its tooltip says
 * why the age is absent. The third says only that the listing was not in the
 * latest sample; it makes no claim about why it is missing.
 */
export default function ListingAge({
  age,
  firstSeenAt,
  status = "active",
  lastSeenAt,
  reason,
}: {
  age?: ListingAgeInfo | null;
  firstSeenAt?: string | null;
  status?: "active" | "no_longer_listed";
  lastSeenAt?: string | null;
  reason?: string | null;
}) {
  if (status === "no_longer_listed") {
    const seen = lastSeenLabel(lastSeenAt);
    return (
      <div className="flex flex-col items-start gap-0.5">
        <Badge tone="neutral">{NO_LONGER_LISTED_LABEL}</Badge>
        {seen && <span className="text-[10px] text-text-dim">{seen}</span>}
      </div>
    );
  }

  const ageLabel = listingAgeLabel(age?.days);
  if (ageLabel) {
    const seen = firstSeenLabel(firstSeenAt);
    return (
      <div className="flex flex-col items-start gap-0.5">
        <Badge tone={age?.tone === "info" ? "info" : "neutral"}>
          {ageLabel}
        </Badge>
        {seen && <span className="text-[10px] text-text-dim">{seen}</span>}
      </div>
    );
  }

  const firstSeen = firstSeenChipLabel(firstSeenAt);
  if (firstSeen) {
    return (
      <Badge
        tone="neutral"
        title={
          reason ||
          "eBay did not return a creation date; this is when this app first saw the listing, not its age."
        }
      >
        {firstSeen}
      </Badge>
    );
  }

  return <span className="text-[10px] text-text-dim">Age not read</span>;
}
