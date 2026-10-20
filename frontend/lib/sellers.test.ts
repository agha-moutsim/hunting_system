import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  SELLER_DISCLAIMER,
  formatAgeStats,
  formatConditionMix,
  formatFeedback,
  formatFeedbackPercentage,
  formatFeedbackScore,
  formatPriceStats,
  formatSellerRegion,
  sellerPagePath,
  sellerPath,
} from "./sellers";

const HERE = dirname(fileURLToPath(import.meta.url));

describe("sellerPath", () => {
  it("trims and encodes the username", () => {
    expect(sellerPath(" agprefect_09 ")).toBe("/api/sellers/agprefect_09");
    expect(sellerPath("name/with space")).toBe(
      "/api/sellers/name%2Fwith%20space"
    );
  });

  it("only adds a query lane when one is supplied", () => {
    expect(sellerPath("agprefect_09", "  garden hose  ")).toBe(
      "/api/sellers/agprefect_09?query=garden+hose"
    );
    expect(sellerPath("agprefect_09", "   ")).toBe("/api/sellers/agprefect_09");
  });

  it("has no parameter that could trigger a live search", () => {
    const path = sellerPath("agprefect_09", "garden hose");
    expect(path).not.toContain("search");
    expect(path).not.toContain("limit");
  });
});

describe("sellerPagePath", () => {
  it("builds the Next.js path and keeps the query context", () => {
    expect(sellerPagePath("agprefect_09", "garden hose")).toBe(
      "/sellers/agprefect_09?query=garden+hose"
    );
    expect(sellerPagePath("agprefect_09")).toBe("/sellers/agprefect_09");
  });
});

describe("feedback formatting", () => {
  it("keeps eBay's percentage with at most two decimals", () => {
    expect(formatFeedbackPercentage(99.8)).toBe("99.8%");
    expect(formatFeedbackPercentage(100)).toBe("100%");
    expect(formatFeedbackPercentage(99.85)).toBe("99.85%");
  });

  it("never turns a missing percentage or score into zero", () => {
    expect(formatFeedbackPercentage(null)).toBeNull();
    expect(formatFeedbackPercentage(Number.NaN)).toBeNull();
    expect(formatFeedbackScore(null)).toBeNull();
  });

  it("groups the feedback score", () => {
    expect(formatFeedbackScore(12431)).toBe("12,431");
    expect(formatFeedbackScore(0)).toBe("0");
  });

  it("does not stitch a percentage to a score it was not read with", () => {
    expect(formatFeedback(99.8, 12431)).toBe("99.8% (12,431)");
    expect(formatFeedback(99.8, null)).toBe("99.8%");
    expect(formatFeedback(null, 12431)).toBe("12,431");
    expect(formatFeedback(null, null)).toBeNull();
  });
});

describe("seller region", () => {
  it("shows country and postal code from the item location", () => {
    expect(formatSellerRegion("GB", "WR4")).toBe("GB - WR4");
    expect(formatSellerRegion("GB", null)).toBe("GB");
    expect(formatSellerRegion(null, "WR4")).toBe("WR4");
    expect(formatSellerRegion(null, null)).toBeNull();
  });
});

describe("condition mix", () => {
  it("uses the known-condition denominator", () => {
    expect(formatConditionMix([{ condition: "New", count: 2, share: 1 }])).toBe(
      "100% New"
    );
    expect(
      formatConditionMix([
        { condition: "New", count: 2, share: 2 / 3 },
        { condition: "Used", count: 1, share: 1 / 3 },
      ])
    ).toBe("66.7% New · 33.3% Used");
  });

  it("has no label when no condition was read", () => {
    expect(formatConditionMix([])).toBeNull();
    expect(formatConditionMix(null)).toBeNull();
  });
});

describe("asking price and age ranges", () => {
  it("keeps the currency on every monetary value", () => {
    expect(
      formatPriceStats({
        currency: "GBP",
        min: 8.99,
        max: 34.99,
        median: 16.99,
        sample: 37,
      })
    ).toBe("GBP 8.99 - GBP 34.99, median GBP 16.99");
    expect(
      formatPriceStats({
        currency: "USD",
        min: 8.99,
        max: 34.99,
        median: 16.99,
        sample: 2,
      })
    ).toBe("USD 8.99 - USD 34.99, median USD 16.99");
  });

  it("does not repeat one price as its own range", () => {
    expect(
      formatPriceStats({
        currency: "GBP",
        min: 16.99,
        max: 16.99,
        median: 16.99,
        sample: 1,
      })
    ).toBe("GBP 16.99");
  });

  it("has no range when the API refused one", () => {
    expect(formatPriceStats(null)).toBeNull();
  });

  it("labels the measured age range without inventing a date", () => {
    expect(formatAgeStats({ min_days: 3, max_days: 210, sample: 37 })).toBe(
      "between 3 and 210 days"
    );
    expect(formatAgeStats({ min_days: 210, max_days: 210, sample: 1 })).toBe(
      "210 days"
    );
    expect(formatAgeStats(null)).toBeNull();
  });
});

describe("the seller panel's copy", () => {
  it("carries the required observed-active-listings disclaimer", () => {
    const page = readFileSync(
      resolve(HERE, "../components/SellerPanel.tsx"),
      "utf8"
    );
    expect(SELLER_DISCLAIMER).toBe(
      "Observed active listings. Nothing here measures what this seller has actually sold."
    );
    expect(page).toContain("{SELLER_DISCLAIMER}");
  });

  it("does not add a revenue, sales or turnover field", () => {
    const source = readFileSync(resolve(HERE, "./sellers.ts"), "utf8");
    for (const word of ["revenue:", "sales:", "turnover:"]) {
      expect(source.toLowerCase()).not.toContain(word);
    }
  });
});
