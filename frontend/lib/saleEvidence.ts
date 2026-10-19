import type { DemandData, ProvenanceInfo, SourcedFigure } from "./types";
import { figureStamp } from "./fieldProvenance";

/**
 * PHASE C — what the Demand section is looking at, decided in one place.
 *
 * Two different numbers can sit under the word "sold": the 7-day count a
 * purchase-history capture read, and a count of live listings a search
 * returned. Only the first is a sale. The rules that keep them apart are the
 * ones a screen must not get wrong, so they are a pure function here rather
 * than a condition inside JSX — this repo has no DOM-testing library, and a
 * rule that lives only in a component is a rule nobody can test.
 *
 *  - a capture-backed figure is the ONLY thing this app calls verified;
 *  - a figure whose source was never recorded is still shown, unverified, and
 *    says so rather than borrowing the badge of the field beside it;
 *  - the search-page note appears exactly when a supply count is on screen and
 *    no verified sale is, so a reader is never shown one without being told
 *    what it is, and a real sales figure never carries the disclaimer.
 */
export interface SaleEvidence {
  /** The 7-day sold figure with its origin, when the payload carries one. */
  figure: SourcedFigure | null;
  /** Its badge, or null when there is no figure to badge. */
  stamp: ProvenanceInfo | null;
  /** True only for a capture-backed figure. */
  verified: boolean;
  /** When the source read it; null when no read time was recorded. */
  readAt: string | null;
  /** The block heading: "Verified sales" vs the honest "Sales evidence". */
  title: string;
  /** Whether anything about sales was measured at all. */
  hasSaleEvidence: boolean;
  /** Whether a search-page count is on screen. */
  hasSearchCount: boolean;
  /** Whether the "that is a search-page count" note is owed to the reader. */
  showsSearchCountNote: boolean;
}

export function saleEvidence(demand?: DemandData | null): SaleEvidence {
  // The triple is authoritative when the payload carries one. The flat key is
  // the older shape, and a row written before origins were recorded is served
  // with no origin — which is what `figureStamp` renders as unverified.
  const figure: SourcedFigure | null =
    demand?.figures?.sold_count_7d ??
    (demand?.sold_count_7d != null
      ? { value: demand.sold_count_7d, origin: null }
      : null);
  const stamp = figureStamp(figure);
  const verified = stamp?.provenance === "verified";
  const hasSearchCount = demand?.active_listings_in_band != null;

  return {
    figure,
    stamp,
    verified,
    readAt: figure?.observed_at ?? null,
    title: verified ? "Verified sales" : "Sales evidence",
    hasSaleEvidence:
      figure != null ||
      demand?.sold_count_30d != null ||
      demand?.avg_sold_price != null ||
      (demand?.sold_prices?.length ?? 0) > 0,
    hasSearchCount,
    showsSearchCountNote: hasSearchCount && !verified,
  };
}
