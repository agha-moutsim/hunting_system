import { describe, expect, it } from "vitest";

import { HEADER_FIELDS, fieldStamp, headerStamps } from "./fieldProvenance";

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
    // row shows eBay avg, Range (min-max) and Best supplier. A new header
    // number added without a stamp here is a number shown bare.
    expect(HEADER_FIELDS).toEqual(
      expect.arrayContaining([
        "ebay_items_sold_month",
        "ebay_total_sold_30d",
        "ebay_total_sold_7d",
        "ebay_avg_price",
        "ebay_price_min",
        "ebay_price_max",
        "best_supplier_price",
      ])
    );
  });
});
