import { describe, expect, it } from "vitest";

import {
  bucketPrices,
  cleanPrices,
  distributionView,
  priceBucketCount,
} from "./buckets";

/**
 * A3 — the arithmetic behind the sold-price chart.
 *
 * If any of these fail, the chart on the Analyze and History pages is
 * drawing something the eBay sold query never returned: a sale counted
 * twice, a sale lost between buckets, or a distribution synthesised over a
 * gap that has no observations in it.
 */

/** The invariants that hold for ANY list of observations. */
function expectCountsCoverEveryObservation(prices: number[]) {
  const buckets = bucketPrices(prices);
  const counted = buckets.reduce((sum, b) => sum + b.count, 0);
  expect(counted).toBe(prices.length);
  expect(counted).toBeGreaterThan(0);
}

describe("cleanPrices", () => {
  it("keeps only real, positive observations", () => {
    expect(cleanPrices([9.99, 12.5, 30])).toEqual([9.99, 12.5, 30]);
  });

  it("drops null, NaN, zero and negative entries", () => {
    // The list arrives from JSON, so its shape is not ours to trust.
    const junk: unknown = [null, 0, -4, Number.NaN, Number.POSITIVE_INFINITY];

    expect(cleanPrices(junk as number[])).toEqual([]);
  });

  it("treats a missing list as no observations", () => {
    expect(cleanPrices(null)).toEqual([]);
    expect(cleanPrices(undefined)).toEqual([]);
  });
});

describe("bucketPrices", () => {
  it("never invents or drops a sale", () => {
    expectCountsCoverEveryObservation([10, 20, 30, 40, 50]);
    expectCountsCoverEveryObservation([9.99, 12.5, 30, 7, 21.25]);
    expectCountsCoverEveryObservation(
      Array.from({ length: 50 }, (_, i) => i + 1)
    );
  });

  it("counts a price sitting exactly on a bucket edge exactly once", () => {
    // min 10, max 50, four buckets of 10 -> [10,20] (20,30] (30,40] (40,50].
    // 20 belongs to the first bucket and to no other, or the sale would be
    // plotted twice and the caption's total would exceed the real one.
    const buckets = bucketPrices([10, 20, 30, 40, 50]);

    expect(buckets).toHaveLength(4);
    expect(buckets[0].lo).toBe(10);
    expect(buckets[0].hi).toBe(20);
    expect(buckets[0].count).toBe(2); // 10 and 20
    expect(buckets[1].count).toBe(1); // 30 only — 20 was not repeated here
    expect(
      buckets[0].count + buckets[1].count + buckets[2].count + buckets[3].count
    ).toBe(5);
  });

  it("collapses a single-price run to one bucket instead of dividing by zero", () => {
    const buckets = bucketPrices([17.99, 17.99, 17.99, 17.99]);

    expect(buckets).toHaveLength(1);
    expect(buckets[0].count).toBe(4);
    expect(buckets[0].range).toBe("17.99");
  });

  it("produces no buckets when nothing was observed", () => {
    expect(bucketPrices([])).toEqual([]);
    expect(bucketPrices(null)).toEqual([]);
    expect(bucketPrices(undefined)).toEqual([]);
    // A gap must render as a gap — never as a synthesised curve.
    const junk: unknown = [null, 0, Number.NaN];
    expect(bucketPrices(junk as number[])).toEqual([]);
  });

  it("labels a single bucket with the price, not with a fake range", () => {
    expect(bucketPrices([12, 12])[0].range).toBe("12.00");
  });

  it("labels every bucket of a spread run with its bounds", () => {
    const buckets = bucketPrices([10, 20, 30, 40, 50]);

    expect(buckets.map((b) => b.range)).toEqual([
      "10–20",
      "20–30",
      "30–40",
      "40–50",
    ]);
  });
});

describe("priceBucketCount", () => {
  it("always gives at least four buckets on a real spread", () => {
    expect(priceBucketCount(3, 20)).toBe(4);
    expect(priceBucketCount(16, 20)).toBe(4);
  });

  it("never gives more than eight, however large the sample", () => {
    expect(priceBucketCount(64, 20)).toBe(8);
    expect(priceBucketCount(1000, 20)).toBe(8);
  });

  it("gives one bucket when there is no spread to divide", () => {
    expect(priceBucketCount(4, 0)).toBe(1);
  });
});

describe("distributionView", () => {
  it("plots when there are at least two observations", () => {
    const view = distributionView([8.0, 9.99, 15.0]);

    expect(view.kind).toBe("chart");
    if (view.kind !== "chart") throw new Error("expected a chart");
    expect(view.observed).toEqual([8.0, 9.99, 15.0]);
    expect(view.min).toBe(8.0);
    expect(view.max).toBe(15.0);
    expect(view.span).toBe(7.0);
  });

  it("says so plainly when nothing was held for the run", () => {
    // The Deep Search path drops sold_prices when it fetches no sold
    // data. Rendering a bar chart over that would assert a market shape
    // that was never observed.
    for (const prices of [null, undefined, []]) {
      const view = distributionView(prices);
      expect(view.kind).toBe("empty");
      if (view.kind !== "empty") continue;
      expect(view.message).toMatch(/no per-sale prices/i);
    }
  });

  it("refuses to draw a distribution from a single sale", () => {
    const view = distributionView([9.99]);

    expect(view.kind).toBe("empty");
    if (view.kind !== "empty") return;
    expect(view.message).toMatch(/not enough to plot/i);
  });

  it("does not plot junk entries that were never a sale", () => {
    // One real observation plus nulls/zeros/NaN: still one, still empty.
    // The list arrives from JSON, so its shape is not ours to trust.
    const junk: unknown = [9.99, 0, null, Number.NaN, -4];

    expect(distributionView(junk as number[]).kind).toBe("empty");
  });

  it("treats two observations as plottable", () => {
    // The threshold is deliberate: two points define a range worth showing.
    expect(distributionView([8, 15]).kind).toBe("chart");
  });
});
