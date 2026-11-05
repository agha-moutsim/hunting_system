import { describe, expect, it } from "vitest";

import { detailAsScorecard, parseFilters } from "./historyDetail";
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

  it("serves no verdict at all when the run saved none", () => {
    const props = detailAsScorecard(
      detail({ verdict: null, profit_computed: undefined })
    );

    expect(props.verdict).toBeNull();
    expect(props.scorecard).toBe("");
    expect(props.profitComputed).toBeUndefined();
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
});
