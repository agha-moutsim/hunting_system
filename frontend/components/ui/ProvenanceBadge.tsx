"use client";

import Badge from "@/components/ui/Badge";
import {
  normalizeProvenance,
  provenanceLabel,
  provenanceTitle,
} from "@/lib/provenance";

const DOTS: Record<string, string> = {
  verified: "bg-brand-lime",
  estimated: "bg-accent-amber",
  unverified: "bg-accent-amber/40",
  ai_insight: "bg-accent-purple",
};

/**
 * Badge for a single provenance stamp.
 *
 * GOLDEN RULE: `provenance` missing, empty or unrecognized renders as
 * `unverified` — a missing stamp is never a confirmation.
 */
export default function ProvenanceBadge({
  provenance,
  label,
  title,
  showLabel = true,
}: {
  provenance?: string;
  label?: string;
  title?: string;
  showLabel?: boolean;
}) {
  const tier = normalizeProvenance(provenance);
  const text = provenanceLabel(provenance, label);
  const tip = title?.trim() || provenanceTitle(provenance);

  if (!showLabel) {
    return (
      <span
        title={tip}
        aria-label={text}
        className={`inline-block w-2 h-2 rounded-full shrink-0 ${DOTS[tier]}`}
      />
    );
  }

  return (
    <Badge tone={tier} title={tip}>
      {text}
    </Badge>
  );
}
