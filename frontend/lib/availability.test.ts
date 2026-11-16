import { describe, expect, it } from "vitest";

import {
  SHIPPING_STATED_NO_AMOUNT,
  SHIPPING_UNKNOWN,
  STOCK_NOT_STATED,
  describeShipping,
  describeStock,
} from "./availability";
import type { MatchAvailabilityFields } from "./types";

/**
 * The availability lines, tested where they now live.
 *
 * The rule these cases protect is the one the sweep is about: a replayed
 * supplier row may not claim to know less than the run recorded. History does
 * not store a shipping amount or its raw text, but it does store
 * `shipping_known`, and "unknown" for such a row is a false absence.
 */

function row(fields: MatchAvailabilityFields): MatchAvailabilityFields {
  return fields;
}

describe("describeShipping", () => {
  it("replays a stated cost as stated, not unknown", () => {
    // 14 stored supplier rows carry shipping_known = 1 with no amount, so the
    // card used to print "Shipping: unknown" over evidence the run recorded.
    const line = describeShipping(row({ shipping_known: true }));

    expect(line.known).toBe(true);
    expect(line.value).toBe(SHIPPING_STATED_NO_AMOUNT);
    expect(line.value).not.toBe(SHIPPING_UNKNOWN);
  });

  it("names the service when the run stored one", () => {
    const line = describeShipping(
      row({ shipping_known: true, shipping_methods: ["Standard Shipping"] })
    );

    expect(line.known).toBe(true);
    expect(line.value).toContain("Standard Shipping");
  });

  it("keeps an explicitly unstated cost unknown", () => {
    for (const fields of [{ shipping_known: false }, { shipping_known: null }, {}]) {
      const line = describeShipping(row(fields));

      expect(line.known).toBe(false);
      expect(line.value).toBe(SHIPPING_UNKNOWN);
    }
  });

  it("still prefers the source's own text and a real amount", () => {
    expect(
      describeShipping(row({ shipping_raw: "Free delivery", shipping_cost: 5 }))
        .value
    ).toBe("Free delivery");
    expect(describeShipping(row({ shipping_cost: 4.5 }), "AUD").value).toBe(
      "A$4.50"
    );
    // 0 is the scraper's "not read" placeholder, not free delivery.
    expect(
      describeShipping(row({ shipping_cost: 0, shipping_days: 3 })).known
    ).toBe(false);
  });
});

describe("describeStock", () => {
  it("shows only a state the source stated", () => {
    expect(describeStock(row({ in_stock: "in_stock" })).value).toBe("In stock");
    expect(describeStock(row({ in_stock: "", stock_raw: "Only 3 left" })).value)
      .toBe("Only 3 left");
  });

  it("keeps an unstated state unknown", () => {
    const line = describeStock(row({}));

    expect(line.known).toBe(false);
    expect(line.value).toBe(STOCK_NOT_STATED);
  });
});
