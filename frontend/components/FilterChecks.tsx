"use client";

import Badge from "@/components/ui/Badge";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import { FilterCheck } from "@/lib/types";
import { normalizeProvenance } from "@/lib/provenance";

const isAdvisory = (f: FilterCheck) =>
  f.advisory === true || f.name === "Delivery (advisory)";

export default function FilterChecks({ filters }: { filters: FilterCheck[] }) {
  const gating = filters.filter((f) => !isAdvisory(f));
  const advisory = filters.filter(isAdvisory);

  return (
    <div>
      <div className="space-y-2">
        {gating.map((f, i) => {
          // Skip only when the badge would repeat the existing Unverified one.
          const duplicateUnverified =
            f.verified === false &&
            normalizeProvenance(f.provenance) === "unverified";
          return (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2 text-sm bg-bg-surface border border-border rounded-control px-3 py-2"
            >
              {f.verified === false ? (
                <Badge tone="warn" title="API could not verify this row">
                  ⚠️ Unverified
                </Badge>
              ) : (
                <Badge tone={f.passed ? "pass" : "fail"}>
                  {f.passed ? "PASS" : "FAIL"}
                </Badge>
              )}
              {f.provenance && !duplicateUnverified && (
                <ProvenanceBadge
                  provenance={f.provenance}
                  label={f.provenance_label}
                />
              )}
              <span className="text-white font-medium">{f.name}</span>
              <span className="text-text-secondary">
                {f.actual}{" "}
                <span className="text-text-dim">(expected {f.expected})</span>
              </span>
            </div>
          );
        })}
      </div>

      {advisory.length > 0 && (
        <div className="mt-2 bg-accent-amber/10 border border-accent-amber/40 rounded-control px-3 py-2">
          {advisory.map((f, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone="warn" title="Advisory — informational, not a gate">
                {f.name.replace(/\s*\(advisory\)\s*/i, "").trim() || f.name}
              </Badge>
              <span className="text-text-secondary">
                {f.actual}{" "}
                <span className="text-text-dim">(expected {f.expected})</span>
              </span>
              <span className="text-xs text-text-dim">
                — confirm your eBay policy
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
