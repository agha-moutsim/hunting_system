import { describe, expect, it } from "vitest";

import {
  HEADER_FIELDS,
  fieldStamp,
  figureStamp,
  headerStamps,
} from "./fieldProvenance";

/**
 * B3 / C13: the label travels with the number.
 *
 * Deep Search showed four header numbers and gave exactly one of them a
 * provenance stamp. These tests hold the rule that a value never reaches
 * the screen bare - a missing stamp renders as Unverified, which is the
 * same golden rule ProvenanceBadge applies to a stamp it cannot read.
 */
describe("fieldStamp", () => {
  it("returns the stamp recorded for the field", () => {
    const stamp = fieldStamp(
      { ebay_avg_price: { provenance: "verified", label: "Verified" } },
      "ebay_avg_price"
    );

    expect(stamp.provenance).toBe("verified");
    expect(stamp.label).toBe("Verified");
  });

  it("falls back to Unverified when the field was never stamped", () => {
    const stamp = fieldStamp({}, "ebay_items_sold_month");

    expect(stamp.provenance).toBe("unverified");
    expect(stamp.label).toBe("Unverified");
  });

  it("falls back when there is no fields map at all", () => {
    expect(fieldStamp(undefined, "ebay_avg_price").provenance).toBe(
      "unverified"
    );
  });

  it("never reports a tier for a stamp that carries none", () => {
    expect(fieldStamp({ x: {} }, "x").provenance).toBe("unverified");
    expect(fieldStamp({ x: { provenance: "" } }, "x").provenance).toBe(
      "unverified"
    );
  });

  it("would never let a missing field read as verified", () => {
    const stamp = fieldStamp({}, "no_such_field");
    expect(stamp.provenance).not.toBe("verified");
    expect(stamp.reason).toBeTruthy();
  });
});

describe("headerStamps", () => {
  const fields = {
    ebay_items_sold_month: { provenance: "ai_insight", label: "AI Insight" },
    ebay_total_sold_30d: { provenance: "verified", label: "Verified" },
    ebay_total_sold_7d: { provenance: "unverified", label: "Unverified" },
    ebay_avg_price: { provenance: "verified", label: "Verified" },
    ebay_price_min: { provenance: "verified", label: "Verified" },
    ebay_price_max: { provenance: "verified", label: "Verified" },
    best_supplier_price: { provenance: "verified", label: "Verified" },
    sold_prices: { provenance: "verified", label: "Verified" },
  };

  it("returns a stamp for every number in the header", () => {
    const stamps = headerStamps(fields);

    for (const name of HEADER_FIELDS) {
      expect(stamps[name], name).toBeTruthy();
      expect(stamps[name].provenance, name).toBeTruthy();
    }
  });

  it("keeps the tier the backend recorded", () => {
    const stamps = headerStamps(fields);

    expect(stamps.ebay_items_sold_month.provenance).toBe("ai_insight");
    expect(stamps.ebay_total_sold_30d.provenance).toBe("verified");
    expect(stamps.ebay_avg_price.provenance).toBe("verified");
  });

  it("marks an unstamped header number Unverified rather than omitting it", () => {
    const stamps = headerStamps({});

    for (const name of HEADER_FIELDS) {
      expect(stamps[name].provenance, name).toBe("unverified");
    }
  });

  it("covers every number the deep-search header actually renders", () => {
    // The meta line shows monthly sales, sold 30d and sold 7d; the tile
    // row shows the price average, Range (min-max) and Best supplier; the
    // chart caption adds the observation count and restates avg and the
    // range. A new header number added without a stamp here is a number
    // shown bare.
    //
    // The caption's count stamp is sold_prices when the run observed sales
    // and active_prices when all it holds is what live listings are asking
    // — a bar chart labelled with the wrong list's provenance is the exact
    // mislabelling the two-list split exists to prevent, so BOTH are
    // required here.
    //
    // Compared in both directions: arrayContaining would let a number
    // reach the page with no entry at all, which is the whole failure
    // this list exists to prevent.
    const rendered = [
      "ebay_items_sold_month",
      "ebay_total_sold_30d",
      "ebay_total_sold_7d",
      "ebay_avg_price",
      "ebay_price_min",
      "ebay_price_max",
      "best_supplier_price",
      "sold_prices",
      "active_prices",
    ];

    expect([...HEADER_FIELDS].sort()).toEqual([...rendered].sort());
  });
});

/**
 * PHASE C: what PRODUCED a stored figure.
 *
 * One source this app can verify — the purchase-history capture read in the
 * user's own signed-in session — and a lot of live-listing counts that are not
 * sales. The badge is chosen by the origin token the backend recorded, never by
 * which slot the number sits in, and an origin nobody recognises never gets the
 * verified look of the field beside it.
 */
describe("figureStamp", () => {
  it("badges a capture-backed figure as verified and names the source", () => {
    const stamp = figureStamp({
      value: 17,
      origin: "purchase_history",
      observed_at: "2026-10-19T19:15:47.505319Z",
    });

    expect(stamp?.provenance).toBe("verified");
    expect(stamp?.label).toBe("eBay purchase history");
  });

  it("returns no badge at all when there is no figure", () => {
    // The half that matters most: a caller cannot stamp a number that was never
    // measured, because there is nothing to pass in.
    expect(figureStamp(null)).toBeNull();
    expect(figureStamp(undefined)).toBeNull();
    expect(figureStamp({})).toBeNull();
    expect(figureStamp({ value: null, origin: "purchase_history" })).toBeNull();
  });

  it("reads a figure whose source was never recorded as unverified", () => {
    const stamp = figureStamp({ value: 7, origin: null });

    expect(stamp?.provenance).toBe("unverified");
    expect(stamp?.label).toBe("Source not recorded");
  });

  it("does not verify an origin it does not know", () => {
    // A token from a newer backend, or a typo. Either way the only honest thing
    // to render is that nobody here can vouch for it - and the token is named so
    // the gap is findable.
    const stamp = figureStamp({ value: 12, origin: "some_new_source" });

    expect(stamp?.provenance).toBe("unverified");
    expect(stamp?.label).toBe("Unrecognised source");
    expect(stamp?.reason).toContain("some_new_source");
  });

  it("treats a blank origin as absent rather than as a name", () => {
    expect(figureStamp({ value: 3, origin: "   " })?.label).toBe(
      "Source not recorded"
    );
  });
});
