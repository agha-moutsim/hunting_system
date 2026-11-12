import { describe, expect, it, vi } from "vitest";

import {
  asUtc,
  formatMoney,
  formatObservedAt,
  formatPrice,
  formatSoldCount,
  marginSortKey,
  priceSortKey,
  profitSortKey,
  timeAgo,
} from "./format";

/**
 * The naive-UTC rule, in one place.
 *
 * Every timestamp this app stores is naive UTC. `new Date()` reads a zone-less
 * string as LOCAL time, so a machine five hours off UTC turns "19:15" into a
 * different instant — which is how the deals board once read "updated 5h ago"
 * while the server's own `stale` flag said the row was current. `asUtc` exists
 * to make those two agree, and these cases pin the rule rather than the
 * implementation that happens to apply it.
 */

describe("asUtc", () => {
  it("reads a zone-less timestamp as UTC, not as local time", () => {
    expect(asUtc("2026-10-19T19:15:00")).toBe(Date.UTC(2026, 9, 19, 19, 15, 0));
  });

  it("leaves an explicitly zoned timestamp alone", () => {
    expect(asUtc("2026-10-19T19:15:00Z")).toBe(
      Date.UTC(2026, 9, 19, 19, 15, 0)
    );
    expect(asUtc("2026-10-19T19:15:00+00:00")).toBe(
      Date.UTC(2026, 9, 19, 19, 15, 0)
    );
    expect(asUtc("2026-10-19T20:15:00+01:00")).toBe(
      Date.UTC(2026, 9, 19, 19, 15, 0)
    );
  });

  it("is NaN, not the epoch, for an empty or unusable value", () => {
    // An epoch would render as 1970 and read as a real observation time.
    expect(asUtc("")).toBeNaN();
    expect(asUtc("not a date")).toBeNaN();
  });
});

describe("formatObservedAt", () => {
  it("prints the instant in UTC and names the zone", () => {
    expect(formatObservedAt("2026-10-19T19:15:47.505319Z")).toBe(
      "19 Oct 2026, 19:15 UTC"
    );
  });

  it("prints the same instant for a naive value as for a Z-tagged one", () => {
    // Same stored moment, two shapes: one row written by this version and one
    // by an older one. They must not read as two different times.
    expect(formatObservedAt("2026-10-19T19:15:47.505319")).toBe(
      formatObservedAt("2026-10-19T19:15:47.505319Z")
    );
  });

  it("never invents a time for a figure that has none", () => {
    // A dash, and explicitly not "now": a read time nobody recorded must not
    // look like a fresh reading.
    expect(formatObservedAt(null)).toBe("\u2014");
    expect(formatObservedAt(undefined)).toBe("\u2014");
    expect(formatObservedAt("")).toBe("\u2014");
    expect(formatObservedAt("rubbish")).toBe("\u2014");
  });
});

describe("timeAgo", () => {
  it("reads a naive timestamp as UTC when measuring how long ago it was", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.UTC(2026, 9, 19, 19, 15, 0)));
    try {
      expect(timeAgo("2026-10-19T19:15:00")).toBe("0s ago");
      expect(timeAgo("2026-10-19T17:15:00")).toBe("2h ago");
      expect(timeAgo("2026-10-17T19:15:00")).toBe("2d ago");
    } finally {
      vi.useRealTimers();
    }
  });

  it("says never rather than 1970 for an unusable value", () => {
    expect(timeAgo("")).toBe("never");
    expect(timeAgo("not a date")).toBe("never");
  });
});

describe("formatMoney", () => {
  it("uses the currency's own symbol, not GBP for every market", () => {
    expect(formatMoney(12.5, "GBP")).toBe("£12.50");
    expect(formatMoney(12.5, "USD")).toBe("$12.50");
    expect(formatMoney(12.5, "EUR")).toBe("€12.50");
    expect(formatMoney(12.5, "AUD")).toBe("A$12.50");
    expect(formatMoney(12.5, "CAD")).toBe("C$12.50");
  });

  it("spells out a code it does not own instead of borrowing a symbol", () => {
    expect(formatMoney(12.5, "JPY")).toBe("12.50 JPY");
  });

  it("never turns an unread amount into zero", () => {
    expect(formatMoney(null, "USD")).toBe("\u2014");
    expect(formatMoney(undefined, "USD")).toBe("\u2014");
  });
});

describe("formatPrice", () => {
  it("prints a real price in its own currency", () => {
    expect(formatPrice(12.5, "GBP")).toBe("£12.50");
    expect(formatPrice(30, "AUD")).toBe("A$30.00");
  });

  it("treats a zero price as unread, not as free", () => {
    // 0 is what the backend sends when a price was never read; printing
    // £0.00 would make an unread listing look like a free one.
    expect(formatPrice(0, "GBP")).toBe("\u2014");
    expect(formatPrice(0, "AUD")).toBe("\u2014");
  });

  it("never invents a price for an absent or impossible value", () => {
    expect(formatPrice(null, "GBP")).toBe("\u2014");
    expect(formatPrice(undefined, "GBP")).toBe("\u2014");
    expect(formatPrice(Number.NaN, "GBP")).toBe("\u2014");
    expect(formatPrice(-5, "GBP")).toBe("\u2014");
  });
});

describe("priceSortKey", () => {
  it("sorts an unread price after every measured one", () => {
    expect(priceSortKey(0)).toBe(Number.POSITIVE_INFINITY);
    expect(priceSortKey(null)).toBe(Number.POSITIVE_INFINITY);
    expect(priceSortKey(undefined)).toBe(Number.POSITIVE_INFINITY);
    expect(priceSortKey(Number.NaN)).toBe(Number.POSITIVE_INFINITY);
    expect(priceSortKey(3.5)).toBe(3.5);
  });
});

describe("profitSortKey", () => {
  it("sorts an unmeasured profit after every measured one, losses included", () => {
    expect(profitSortKey(null)).toBe(Number.POSITIVE_INFINITY);
    expect(profitSortKey(undefined)).toBe(Number.POSITIVE_INFINITY);
    expect(profitSortKey(Number.NaN)).toBe(Number.POSITIVE_INFINITY);
    // A real loss is a measurement and keeps its own place.
    expect(profitSortKey(-5.5)).toBe(-5.5);
    expect(profitSortKey(0)).toBe(0);
  });
});

describe("marginSortKey", () => {
  it("sorts an unmeasured margin after every measured one", () => {
    expect(marginSortKey(null)).toBe(Number.POSITIVE_INFINITY);
    expect(marginSortKey(undefined)).toBe(Number.POSITIVE_INFINITY);
    expect(marginSortKey(Number.NaN)).toBe(Number.POSITIVE_INFINITY);
    // A negative margin is a measurement, and break-even is not absence.
    expect(marginSortKey(-12.5)).toBe(-12.5);
    expect(marginSortKey(0)).toBe(0);
  });
});

describe("formatSoldCount", () => {
  it("prints a count that was actually observed", () => {
    expect(formatSoldCount(30)).toBe("30");
    expect(formatSoldCount(1)).toBe("1");
  });

  it("prints a dash for the unread zero default", () => {
    // The payload cannot tell a measured zero from the default, so it must
    // not claim "Sold 30d: 0" as a reading.
    expect(formatSoldCount(0)).toBe("\u2014");
    expect(formatSoldCount(null)).toBe("\u2014");
    expect(formatSoldCount(undefined)).toBe("\u2014");
    expect(formatSoldCount(Number.NaN)).toBe("\u2014");
  });
});
