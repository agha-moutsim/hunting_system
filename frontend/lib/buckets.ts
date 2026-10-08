/**
 * A3 — binning of observed sold prices.
 *
 * Deliberately free of React and recharts: this is the arithmetic the chart
 * is built on, so it can be asserted on its own. Three rules carry the
 * honesty of the whole feature:
 *
 *  1. the counts of all buckets sum to the number of observations — no sale
 *     is invented, none is dropped;
 *  2. a price sitting exactly on a bucket edge falls in exactly one bucket;
 *  3. span === 0 (every sale at one price) collapses to a single bucket
 *     rather than dividing by zero.
 */

export interface PriceBucket {
  /** Inclusive-or-exclusive bounds actually used for counting. */
  lo: number;
  hi: number;
  /** Axis label. Single bucket shows the price itself, not a fake range. */
  range: string;
  count: number;
}

/**
 * Keep only prices that are real, positive observations. A null/NaN/0 entry
 * reaching the chart would be a data point nobody ever observed.
 */
export function cleanPrices(prices?: number[] | null): number[] {
  return (prices || []).filter((p) => Number.isFinite(p) && p > 0);
}

/**
 * Enough buckets to show shape, few enough that a 10-sale run still has bars
 * worth reading: between 4 and 8, sized by the square root of the sample.
 */
export function priceBucketCount(n: number, span: number): number {
  if (span === 0) return 1;
  return Math.min(8, Math.max(4, Math.ceil(Math.sqrt(n))));
}

export function bucketPrices(prices?: number[] | null): PriceBucket[] {
  const observed = cleanPrices(prices);
  if (!observed.length) return [];

  const min = Math.min(...observed);
  const max = Math.max(...observed);
  const span = max - min;
  const bucketCount = priceBucketCount(observed.length, span);
  // span === 0 needs a nonzero width so the loop has a stride, but the last
  // bucket's `hi` is always pinned to max, so nothing is counted twice.
  const width = span === 0 ? 1 : span / bucketCount;

  return Array.from({ length: bucketCount }, (_, i) => {
    const lo = min + i * width;
    const last = i === bucketCount - 1;
    const hi = last ? max : lo + width;
    // (lo, hi] for every bucket after the first, [lo, hi] for the first —
    // a price sitting exactly on an edge is counted once, in one bucket.
    const count = observed.filter(
      (p) => (i === 0 ? p >= lo : p > lo) && p <= hi
    ).length;
    return {
      lo,
      hi,
      count,
      range:
        bucketCount === 1
          ? min.toFixed(2)
          : `${lo.toFixed(0)}–${hi.toFixed(0)}`,
    };
  });
}

/**
 * What the distribution chart should draw for one run's observations.
 *
 * Kept out of the component so the decision between plotting and saying
 * "nothing to plot" can be asserted. Two points is the threshold: with
 * one there is no shape, only a min and a max the tiles already show, and
 * drawing a bar over an empty run would assert a market that was never
 * observed.
 */
export type DistributionView =
  | { kind: "empty"; message: string }
  | {
      kind: "chart";
      observed: number[];
      min: number;
      max: number;
      span: number;
    };

export function distributionView(prices?: number[] | null): DistributionView {
  const observed = cleanPrices(prices);

  if (observed.length < 2) {
    return {
      kind: "empty",
      message:
        observed.length === 0
          ? "No per-sale prices were held for this run."
          : "One sale observed — not enough to plot a distribution.",
    };
  }

  const min = Math.min(...observed);
  const max = Math.max(...observed);
  return { kind: "chart", observed, min, max, span: max - min };
}
