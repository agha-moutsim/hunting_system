import { describe, expect, it } from "vitest";

import { demandSourceRows, deepSearchUnknowns } from "./sourcesRows";
import type { DeepSearchResult, DemandData } from "./types";

/**
 * PHASE C — the Sources rows, and the rule the screen exists to hold.
 *
 *   "the unknowns list, generated from which fields are null — not
 *    hard-coded prose"
 *
 * So these cases test the derivation rather than the wording: which rows land
 * in "measured", which land in "not known", and the two ways a value could be
 * mistaken for its absence — a real zero, and an empty list.
 */

function byName(rows: ReturnType<typeof demandSourceRows>) {
  return Object.fromEntries(rows.map((r) => [r.name, r]));
}

const CAPTURED: DemandData = {
  figures: {
    sold_count_7d: {
      value: 17,
      origin: "purchase_history",
      observed_at: "2026-10-19T19:15:47.505319Z",
    },
    sold_count_30d: null,
  },
  active_listings_in_band: 50,
  avg_active_price: 21.99,
  lowest_active_price: 9.5,
  highest_active_price: 39.99,
  active_prices: [9.5, 12, 39.99],
};

describe("demandSourceRows", () => {
  it("stamps a captured sale with its source and the moment it was read", () => {
    const row = byName(demandSourceRows(CAPTURED)).sold_count_7d;

    expect(row.value).toBe("17");
    expect(row.stamp?.provenance).toBe("verified");
    expect(row.stamp?.label).toBe("eBay purchase history");
    expect(row.readAt).toBe("19 Oct 2026, 19:15 UTC");
  });

  it("keeps a legacy count that predates origins, measured but unattributed", () => {
    const row = byName(demandSourceRows({ sold_count_7d: 7 })).sold_count_7d;

    expect(row.value).toBe("7");
    expect(row.stamp?.label).toBe("Source not recorded");
    expect(row.readAt).toBeNull();
  });

  it("treats a real zero as a measurement, never as an unknown", () => {
    // The distinction the whole screen turns on. A search that returned no
    // in-band listing knows something: it measured nothing for sale. Rendering
    // that as "not known" would throw away a real reading, and rendering an
    // absent value as 0 is the error this repo has fixed twice before.
    const rows = byName(demandSourceRows({ active_listings_in_band: 0 }));

    expect(rows.active_listings_in_band.value).toBe("0");
    expect(rows.avg_active_price.value).toBeNull();
  });

  it("reads an empty price list as nothing observed, not as a count of zero", () => {
    const rows = byName(
      demandSourceRows({ sold_prices: [], active_prices: [] })
    );

    expect(rows.sold_prices.value).toBeNull();
    expect(rows.active_prices.value).toBeNull();
  });

  it("marks a supply figure as supply and a sale figure as not", () => {
    const rows = byName(demandSourceRows(CAPTURED));

    expect(rows.sold_count_7d.supply).toBeUndefined();
    expect(rows.avg_active_price.supply).toBe(true);
    expect(rows.active_listings_in_band.supply).toBe(true);
  });

  it("renders a range only when both ends were measured", () => {
    // A one-ended range is not a range, and a "£9.50 – —" would read as a
    // measurement of the other end.
    const rows = byName(demandSourceRows({ lowest_active_price: 9.5 }));

    expect(rows.active_price_range.value).toBeNull();
    expect(rows.active_price_range.unknownReason).not.toBe("");
    expect(byName(demandSourceRows(CAPTURED)).active_price_range.value).toBe(
      "£9.50 – £39.99"
    );
  });

  it("gives every row an id, a name and a reason for its absence", () => {
    // Structural incompleteness is what makes an unknown list blank in the odd
    // row. Every row has to be renderable in either list.
    const rows = demandSourceRows(null);

    expect(rows.length).toBeGreaterThan(0);
    const names = rows.map((r) => r.name);
    expect(new Set(names).size).toBe(names.length);
    for (const row of rows) {
      expect(row.label.trim()).not.toBe("");
      expect(row.unknownReason.trim()).not.toBe("");
      expect(row.value).toBeNull();
    }
  });

  it("turns an absent demand row into all-unknowns rather than an error", () => {
    for (const empty of [null, undefined, {}]) {
      const rows = demandSourceRows(empty as DemandData | null | undefined);
      expect(rows.every((r) => r.value === null)).toBe(true);
    }
  });

  it("names the fields the API actually serves", () => {
    // These strings are the payload keys and the database columns. A rename in
    // the API that leaves this list behind would show a reader a key that no
    // longer exists, which is a citation to a field that is not there.
    const names = demandSourceRows(CAPTURED).map((r) => r.name);

    expect(names).toContain("sold_count_7d");
    expect(names).toContain("sold_count_30d");
    expect(names).toContain("active_listings_in_band");
    expect(names).toContain("avg_sold_price");
    expect(names).toContain("last_sale_date");
  });
});

/**
 * The same derivation for a Deep Search run, which has no stored product to
 * point `/sources` at. The rule has to be the same one: a field with no value
 * is an unknown, and it stops being one the moment a source fills it.
 */
describe("deepSearchUnknowns", () => {
  const EMPTY_RUN = {
    product_name: "Dyson ball animal 2",
    ebay_total_sold_7d: null,
    sold_prices: [],
    active_prices: [],
    ebay_top_sellers: [],
    suppliers: [],
  } as unknown as DeepSearchResult;

  it("lists every field the run did not fill", () => {
    const names = deepSearchUnknowns(EMPTY_RUN).map((u) => u.name);

    expect(names).toEqual([
      "ebay_total_sold_7d",
      "sold_prices",
      "active_prices",
      "ebay_top_sellers",
      "suppliers",
    ]);
  });

  it("drops a field as soon as the run fills it", () => {
    // The list is a reading of the payload, so it has to shrink by itself. A
    // hard-coded paragraph would still be claiming this gap after a source
    // filled it.
    const filled = {
      ...EMPTY_RUN,
      ebay_total_sold_7d: 17,
      active_prices: [9.5, 12],
      suppliers: [{ supplier_name: "AliExpress" }],
    } as unknown as DeepSearchResult;

    const names = deepSearchUnknowns(filled).map((u) => u.name);

    expect(names).toEqual(["sold_prices", "ebay_top_sellers"]);
  });

  it("every row says what the gap is and what would close it", () => {
    const rows = deepSearchUnknowns(EMPTY_RUN);
    expect(new Set(rows.map((r) => r.name)).size).toBe(rows.length);
    for (const row of rows) {
      expect(row.label.trim()).not.toBe("");
      expect(row.reason.trim()).not.toBe("");
    }
  });

  it("says nothing at all when there is no run to describe", () => {
    // Not "everything is unknown": with no result there is no claim to make,
    // and a card full of gaps would invent a run that never happened.
    expect(deepSearchUnknowns(null)).toEqual([]);
    expect(deepSearchUnknowns(undefined)).toEqual([]);
  });
});
