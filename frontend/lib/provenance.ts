/** Provenance helpers (C13) — one place for the golden rule. */

import { ProvenanceInfo } from "@/lib/types";

export const PROVENANCE_TIERS = [
  "verified",
  "estimated",
  "unverified",
  "ai_insight",
] as const;

const DEFAULT_LABELS: Record<string, string> = {
  verified: "Verified",
  estimated: "Estimated",
  unverified: "Unverified",
  ai_insight: "AI Insight",
};

const TITLES: Record<string, string> = {
  verified: "Read from a real API response or a parsed page",
  estimated: "Computed by a stated method — not directly observed",
  unverified: "Could not be confirmed — shown, but never gates a verdict",
  ai_insight: "LLM analysis — never a source of fact",
};

/** Separator/case folding only — anything else stays unrecognized. */
const ALIASES: Record<string, string> = {
  estimate: "estimated",
  aiinsight: "ai_insight",
  ai_analysis: "ai_insight",
};

/**
 * GOLDEN RULE: missing, empty or unrecognized provenance is "unverified".
 * A missing stamp is never a confirmation (mirrors backend `_prov_of()`).
 */
export function normalizeProvenance(p?: string | null): string {
  if (p == null) return "unverified";
  const key = String(p)
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  if (!key) return "unverified";
  const alias = ALIASES[key];
  if (alias) return alias;
  return (PROVENANCE_TIERS as readonly string[]).includes(key)
    ? key
    : "unverified";
}

/** Display label: the backend's own label wins, else the tier default. */
export function provenanceLabel(p?: string | null, label?: string | null) {
  const given = (label ?? "").trim();
  return given || DEFAULT_LABELS[normalizeProvenance(p)];
}

/** Tooltip text: caller-provided wins, else a short explanation of the tier. */
export function provenanceTitle(p?: string | null, fallback?: string | null) {
  const given = (fallback ?? "").trim();
  return given || TITLES[normalizeProvenance(p)];
}

/** Best tooltip for a whole ProvenanceInfo entry (method/reason/source). */
export function infoTitle(info?: ProvenanceInfo): string | undefined {
  const text = [info?.method, info?.reason, info?.source_name, info?.source_url]
    .map((s) => (s ?? "").trim())
    .filter(Boolean)
    .join(" · ");
  return text || undefined;
}

/**
 * Look up one field inside a `provenance.fields` map.
 * Accepts exact keys ("demand.sold_count_30d") or bare names matched on the
 * last path segment ("sold_count_30d"). Returns undefined when absent so the
 * caller can fall back to existing behaviour instead of faking a stamp.
 */
export function fieldProvenance(
  fields: Record<string, ProvenanceInfo> | undefined,
  ...names: string[]
): ProvenanceInfo | undefined {
  if (!fields) return undefined;
  for (const name of names) {
    if (fields[name]) return fields[name];
    const tail = name.split(".").pop();
    for (const key of Object.keys(fields)) {
      if (key === name || key.split(".").pop() === tail) return fields[key];
    }
  }
  return undefined;
}
