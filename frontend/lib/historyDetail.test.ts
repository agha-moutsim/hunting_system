import { describe, expect, it } from "vitest";

import { detailAsScorecard, legacyPlaceholderWarning, parseFilters } from "./historyDetail";
import type { ProductDetail } from "./types";

/**
 * The History detail → Scorecard translation, tested where it now lives.
 *
 * The page used to do this inline, which meant the C1 rule ("a null figure
 * stays null") was enforced by a character in a JSX file and could only be
 * checked on a live screen. These tests pin the boundary: whatever the API
 * said about a figure is what the component receives.
 */

function detail(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    product: {
      id: 32,
      title: "Stainless Steel Water Bottle",
      price: 12.5,
      condition: "New",
      format: "Buy It Now",
      seller: "bottle-shop",
      ebay_url: "https://www.ebay.co.uk/itm/32",
    },
    demand: null,
    suppliers: [],
    analysis: null,
    profit_computed: false,
    verdict: {
      verdict: "fail",
      profit_amount: null,
      profit_margin: null,
      filter_results: [],
      scorecard: "no supplier price - not computed",
    },
    ...overrides,
  };
}

describe("detailAsScorecard", () => {
  it("keeps an uncomputed profit and margin null", () => {
    const props = detailAsScorecard(detail());

    expect(props.verdict?.profit).toBeNull();
    expect(props.verdict?.margin).toBeNull();
    expect(props.profitComputed).toBe(false);
  });

  it("keeps a measured zero as zero", () => {
    const props = detailAsScorecard(
      detail({
        profit_computed: true,
        verdict: {
          verdict: "fail",
          profit_amount: 0,
          profit_margin: 0,
          filter_results: [],
        },
      })
    );

    expect(props.verdict?.profit).toBe(0);
    expect(props.verdict?.margin).toBe(0);
    expect(props.profitComputed).toBe(true);
  });

  it("parses filter rows saved as a JSON string", () => {
    const props = detailAsScorecard(
      detail({
        verdict: {
          verdict: "pending",
          profit_amount: null,
          profit_margin: null,
          filter_results: JSON.stringify([
            { name: "Margin", passed: false, verified: false },
          ]),
        },
      })
    );

    expect(props.verdict?.filters).toEqual([
      { name: "Margin", passed: false, verified: false },
    ]);
  });

  it("returns no filters for malformed stored JSON", () => {
    const props = detailAsScorecard(
      detail({
        verdict: {
          verdict: "pending",
          profit_amount: null,
          profit_margin: null,
          filter_results: "{not json",
        },
      })
    );

    expect(props.verdict?.filters).toEqual([]);
  });

  it("does not invent a verification for a supplier that never stated one", () => {
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "AliExpress",
            supplier_price: 7.64,
            provenance: null,
            provenance_label: null,
            verified: null,
            fetch_method: null,
          },
        ],
      })
    );

    const supplier = props.suppliers[0];
    expect(supplier.provenance).toBeUndefined();
    expect(supplier.provenance_label).toBeUndefined();
    expect(supplier.verified).toBeUndefined();
    expect(supplier.fetch_method).toBeUndefined();
  });

  it("replays the stored match score but never a tier", () => {
    // The database holds the score and not the tier. The component may show
    // the measurement; it must not be handed a classification to print.
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "AliExpress",
            supplier_price: 7.64,
            match_score: 0.5885,
          },
          {
            supplier_name: "AliExpress",
            supplier_price: 11.2,
            match_score: null,
          },
        ],
      })
    );

    expect(props.suppliers[0].match_score).toBe(0.5885);
    expect(props.suppliers[1].match_score).toBeUndefined();
    expect(props.suppliers[0].match_tier).toBeUndefined();
  });

  it("replays a stock state only when the source stated it", () => {
    // Product 50's B&Q rows store stock_status "in_stock" with the verified
    // flag. Dropping them made a stated stock read as "not stated".
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "B&Q",
            supplier_price: 7.64,
            stock_status: "in_stock",
            stock_verified: true,
          },
          {
            supplier_name: "B&Q",
            supplier_price: 7.64,
            stock_status: "in_stock",
            stock_verified: false,
          },
          {
            supplier_name: "B&Q",
            supplier_price: 7.64,
            stock_status: "unknown",
            stock_verified: true,
          },
        ],
      })
    );

    expect(props.suppliers[0].in_stock).toBe("in_stock");
    expect(props.suppliers[1].in_stock).toBeUndefined();
    expect(props.suppliers[2].in_stock).toBeUndefined();
  });

  it("replays the sourcing assessment the run stored", () => {
    // Product 50's B&Q rows carry sourcing_preferred with its reasons. The
    // replay dropped the block, so the badge the live screen showed never
    // reached History.
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "B&Q",
            supplier_price: 7.64,
            sourcing_preferred: true,
            sourcing_eligible: true,
            sourcing_reasons: ["review rating not read"],
            sourcing_score: 73.5,
            sourcing_policy_version: "2026-09",
          },
        ],
      })
    );

    const supplier = props.suppliers[0];
    expect(supplier.sourcing_preferred).toBe(true);
    expect(supplier.sourcing_eligible).toBe(true);
    expect(supplier.sourcing_reasons).toEqual(["review rating not read"]);
    expect(supplier.sourcing_score).toBe(73.5);
    expect(supplier.sourcing_policy_version).toBe("2026-09");
  });

  it("keeps an unassessed sourcing block absent", () => {
    // NULL means the run never assessed this row — not "not preferred".
    const props = detailAsScorecard(
      detail({
        suppliers: [{ supplier_name: "AliExpress", supplier_price: 7.64 }],
      })
    );

    const supplier = props.suppliers[0];
    expect(supplier.sourcing_preferred).toBeUndefined();
    expect(supplier.sourcing_eligible).toBeUndefined();
    expect(supplier.sourcing_reasons).toBeUndefined();
  });

  it("replays a stored landed cost and keeps an absent one absent", () => {
    // 14 stored supplier rows carry the landed cost the run computed. The
    // replay dropped it while the API served it; NULL must stay absent rather
    // than become a free postage figure.
    const props = detailAsScorecard(
      detail({
        suppliers: [
          { supplier_name: "B&Q", supplier_price: 7.64, total_landed_cost: 10.99 },
          { supplier_name: "B&Q", supplier_price: 7.64, total_landed_cost: null },
        ],
      })
    );

    expect(props.suppliers[0].total_landed_cost).toBe(10.99);
    expect(props.suppliers[1].total_landed_cost).toBeUndefined();
  });

  it("replays a verified review and leaves an unverified one off the card", () => {
    // 38 stored supplier rows carry a rating the source stated, with the
    // verified flag and its source. Dropping them made History's cards show no
    // review while the live card had shown one.
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "AliExpress",
            supplier_price: 7.64,
            review_rating: 4.9,
            review_verified: true,
            review_source: "rapidapi",
          },
          {
            supplier_name: "AliExpress",
            supplier_price: 7.64,
            review_rating: 3.2,
            review_verified: false,
            review_source: "rapidapi",
          },
          { supplier_name: "B&Q", supplier_price: 7.64 },
        ],
      })
    );

    expect(props.suppliers[0].review_rating).toBe(4.9);
    expect(props.suppliers[0].review_verified).toBe(true);
    expect(props.suppliers[0].review_source).toBe("rapidapi");
    // The card gates on the verified flag, so a false reading can be carried
    // without being printed as one.
    expect(props.suppliers[1].review_verified).toBe(false);
    expect(props.suppliers[2].review_rating).toBeUndefined();
    expect(props.suppliers[2].review_verified).toBeUndefined();
  });

  it("replays the stored shipping statement with the row", () => {
    // Neither the amount nor the raw text is stored, but the run recorded
    // whether the source stated a cost. Without this flag the card called a
    // stated cost "unknown" on every replayed B&Q row.
    const props = detailAsScorecard(
      detail({
        suppliers: [
          {
            supplier_name: "B&Q",
            supplier_price: 7.64,
            shipping_known: true,
            shipping_methods: ["Standard Shipping"],
          },
          { supplier_name: "B&Q", supplier_price: 7.64, shipping_known: null },
        ],
      })
    );

    expect(props.suppliers[0].shipping_known).toBe(true);
    expect(props.suppliers[0].shipping_methods).toEqual(["Standard Shipping"]);
    // NULL was never a statement, so it stays absent rather than becoming
    // `false`, which would read as "the source said nothing" on replay.
    expect(props.suppliers[1].shipping_known).toBeUndefined();
  });

  it("keeps an empty stored verdict empty, not pending", () => {
    const props = detailAsScorecard(
      detail({
        verdict: {
          verdict: "",
          profit_amount: null,
          profit_margin: null,
          filter_results: [],
        },
      })
    );

    expect(props.verdict?.verdict).toBe("");
  });

  it("serves no verdict at all when the run saved none", () => {
    const props = detailAsScorecard(
      detail({ verdict: null, profit_computed: undefined })
    );

    expect(props.verdict).toBeNull();
    expect(props.scorecard).toBe("");
    expect(props.profitComputed).toBeUndefined();
    expect(props.scorecardWarning).toBeNull();
  });

  it("flags a legacy scorecard that still prints placeholder money", () => {
    const props = detailAsScorecard(
      detail({
        verdict: {
          verdict: "fail",
          profit_amount: null,
          profit_margin: null,
          filter_results: [],
          scorecard: "  Profit:         £0.00\n  Margin:         0.0%",
        },
      })
    );

    expect(props.scorecardWarning).toContain("placeholders");
  });

  it("does not flag a scorecard that already says not computed", () => {
    const props = detailAsScorecard(detail());

    expect(props.scorecardWarning).toBeNull();
  });

  it("replays the stored currency instead of relabelling AUD as pounds", () => {
    const base = detail();
    const props = detailAsScorecard({
      ...base,
      product: { ...base.product, marketplace: "EBAY_AU", currency: "AUD" },
    });

    expect(props.currency).toBe("AUD");
    expect(props.ebayProduct.currency).toBe("AUD");
    expect(props.ebayProduct.source).toBe("eBay AU");
  });

  it("falls back to pounds only when the row never stated a currency", () => {
    const props = detailAsScorecard(detail());

    expect(props.currency).toBe("GBP");
    expect(props.ebayProduct.currency).toBe("GBP");
  });
});

describe("legacyPlaceholderWarning", () => {
  const legacy = "  Profit:         £0.00\n  Margin:         0.0%";

  it("warns for an uncomputed verdict whose stored text prints zeros", () => {
    expect(legacyPlaceholderWarning(legacy, false)).toContain("placeholders");
  });

  it("stays quiet for a computed break-even", () => {
    expect(legacyPlaceholderWarning(legacy, true)).toBeNull();
  });

  it("stays quiet when the flag was never recorded", () => {
    expect(legacyPlaceholderWarning(legacy, undefined)).toBeNull();
  });
});

describe("parseFilters", () => {
  it("accepts an already-decoded array", () => {
    expect(parseFilters([{ name: "Margin", passed: true }])).toHaveLength(1);
  });

  it("treats absent and non-array values as no rows", () => {
    expect(parseFilters(undefined)).toEqual([]);
    expect(parseFilters(null)).toEqual([]);
    expect(parseFilters('{"name":"Margin"}')).toEqual([]);
  });

  it("replays a legacy N/A demand count as not read", () => {
    // 50 stored UK verdicts say "N/A" for the 7-day demand count. N/A is not a
    // measurement, so the replayed row keeps its absence in words (C1).
    const rows = parseFilters(
      JSON.stringify([
        { name: "Demand (7d)", passed: false, actual: "N/A", verified: false },
      ])
    );

    expect(rows[0].actual).toBe("not read");
    expect(rows[0].verified).toBe(false);
  });

  it("leaves a real reading alone", () => {
    const rows = parseFilters([
      { name: "Demand (7d)", passed: true, actual: "12 sold" },
    ]);

    expect(rows[0].actual).toBe("12 sold");
  });
});
