import { describe, expect, it, vi } from "vitest";

import { asUtc, formatMoney, formatObservedAt, timeAgo } from "./format";

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
