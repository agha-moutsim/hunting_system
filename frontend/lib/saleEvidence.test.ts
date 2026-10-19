import { describe, expect, it } from "vitest";

import { saleEvidence } from "./saleEvidence";
import type { DemandData } from "./types";

/**
 * The Phase C acceptance, as rules rather than as screenshots.
 *
 *   "Open a product with a capture: verified figure first with the capture
 *    date. Open one without: search count, correctly labelled, plus the
 *    explanatory sentence."
 *
 * Both halves are asserted here, and so is the case where the two numbers are
 * on screen together and only one of them may wear the verified badge.
 */

const CAPTURED: DemandData = {
  active_listings_in_band: 50,
  avg_active_price: 21.99,
  figures: {
    sold_count_7d: {
      value: 17,
      origin: "purchase_history",
      observed_at: "2026-10-19T19:15:47.505319Z",
    },
    sold_count_30d: null,
  },
};

const SEARCH_ONLY: DemandData = {
  active_listings_in_band: 50,
  avg_active_price: 21.99,
  avg_active_price_label: undefined,
  figures: { sold_count_7d: null, sold_count_30d: null },
} as DemandData;

describe("saleEvidence", () => {
  it("makes a capture-backed figure primary, with the date it was read", () => {
    const view = saleEvidence(CAPTURED);

    expect(view.verified).toBe(true);
    expect(view.title).toBe("Verified sales");
    expect(view.figure?.value).toBe(17);
    expect(view.stamp?.label).toBe("eBay purchase history");
    expect(view.readAt).toBe("2026-10-19T19:15:47.505319Z");
  });

  it("shows a search-page count without calling it a sale", () => {
    const view = saleEvidence(SEARCH_ONLY);

    expect(view.verified).toBe(false);
    expect(view.title).toBe("Sales evidence");
    expect(view.hasSearchCount).toBe(true);
    expect(view.showsSearchCountNote).toBe(true);
  });

  it("never puts the search-page note under a verified sale", () => {
    // The capture run ALSO holds a search count. The note belongs to the count,
    // and the count is not the headline any more.
    const view = saleEvidence(CAPTURED);

    expect(view.hasSearchCount).toBe(true);
    expect(view.showsSearchCountNote).toBe(false);
  });

  it("keeps a legacy count that predates origins, unverified and unattributed", () => {
    const view = saleEvidence({
      sold_count_7d: 7,
      active_listings_in_band: 50,
    });

    expect(view.figure?.value).toBe(7);
    expect(view.verified).toBe(false);
    expect(view.stamp?.label).toBe("Source not recorded");
    expect(view.readAt).toBeNull();
  });

  it("owes the reader no note when no search count was ever read", () => {
    const view = saleEvidence({ figures: { sold_count_7d: null } });

    expect(view.hasSaleEvidence).toBe(false);
    expect(view.hasSearchCount).toBe(false);
    expect(view.showsSearchCountNote).toBe(false);
  });

  it("treats a missing demand block as no evidence, not as zero", () => {
    for (const empty of [null, undefined, {}]) {
      const view = saleEvidence(empty as DemandData | null | undefined);
      expect(view.figure).toBeNull();
      expect(view.stamp).toBeNull();
      expect(view.hasSaleEvidence).toBe(false);
      expect(view.hasSearchCount).toBe(false);
    }
  });

  it("shows a sold price with no count as sale evidence", () => {
    // Only a capture can produce a sale price, so this is evidence even
    // without a count beside it. It arrives unverified if it does not say
    // where it came from.
    const view = saleEvidence({ avg_sold_price: 12.99, sold_count_7d: null });

    expect(view.hasSaleEvidence).toBe(true);
    expect(view.verified).toBe(false);
    expect(view.showsSearchCountNote).toBe(false);
  });
});
