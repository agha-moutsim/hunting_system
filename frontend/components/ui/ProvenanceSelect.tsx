"use client";

import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import {
  PROVENANCE_TIERS,
  provenanceLabel,
  provenanceTitle,
} from "@/lib/provenance";

/** Legend of the four provenance tiers (C13) — for panel headers. */
export default function ProvenanceSelect({
  className = "",
}: {
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <span className="text-xs text-text-dim">Provenance</span>
      {PROVENANCE_TIERS.map((tier) => (
        <ProvenanceBadge
          key={tier}
          provenance={tier}
          label={provenanceLabel(tier)}
          title={provenanceTitle(tier)}
        />
      ))}
    </div>
  );
}
