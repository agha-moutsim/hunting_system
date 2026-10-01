"use client";

import Badge from "@/components/ui/Badge";
import { MatchTier } from "@/lib/types";

/**
 * Fallback copy for the availability lines. It lives here so every caller
 * renders an unknown value the same way — an unknown never becomes a claim.
 */
export const STOCK_NOT_STATED = "Stock: not stated";
export const SHIPPING_UNKNOWN = "Shipping: unknown";

/** Tiers a badge may be drawn for. `""`/absent/unknown is NOT in this list. */
const MATCH_TIERS = ["verified", "unverified", "no_match"] as const;

const TONE: Record<string, string> = {
  verified: "verified",
  unverified: "unverified",
  no_match: "unverified",
};

const DEFAULT_TEXT: Record<string, string> = {
  verified: "Match verified",
  unverified: "Match not confirmed",
  no_match: "No confirmed match",
};

export interface MatchDescription {
  tone: string;
  text: string;
  /** Tooltip only — never the card body. */
  title?: string;
  /** True when a real, finite score was present and is shown in `text`. */
  scored: boolean;
}

/**
 * A score is shown only when it is a real finite number, at exactly 2dp.
 * Anything else returns null so no score can be invented or coerced.
 */
export function formatMatchScore(score?: number | null): string | null {
  if (typeof score !== "number" || !Number.isFinite(score)) return null;
  return score.toFixed(2);
}

/**
 * GOLDEN RULE: an unscored row (`""`, null, absent or unrecognised) has no
 * description at all — it must not look like a match in either direction.
 * Unlike `ProvenanceBadge`, which always draws a stamp, this returns null so
 * the caller renders nothing.
 */
export function describeMatchTier(
  tier?: MatchTier | string | null,
  fields: {
    score?: number | null;
    label?: string | null;
    basis?: string | null;
    method?: string | null;
  } = {}
): MatchDescription | null {
  const key = String(tier ?? "")
    .trim()
    .toLowerCase();
  if (!key || !(MATCH_TIERS as readonly string[]).includes(key)) return null;

  const given = (fields.label ?? "").trim();
  const score = key === "verified" ? formatMatchScore(fields.score) : null;
  const title =
    [fields.basis, fields.method]
      .map((s) => (s ?? "").trim())
      .filter(Boolean)
      .join(" · ") || undefined;

  return {
    tone: TONE[key],
    text: score ? `Match ${score}` : given || DEFAULT_TEXT[key],
    title,
    scored: score != null,
  };
}

/**
 * Badge for a product-match tier. Renders nothing at all when the row was
 * never scored — a placeholder would read as a verdict.
 */
export default function MatchBadge({
  tier,
  score,
  label,
  basis,
  method,
}: {
  tier?: MatchTier | string | null;
  score?: number | null;
  label?: string | null;
  basis?: string | null;
  method?: string | null;
}) {
  const match = describeMatchTier(tier, { score, label, basis, method });
  if (!match) return null;
  return (
    <Badge tone={match.tone} title={match.title}>
      {match.text}
    </Badge>
  );
}
