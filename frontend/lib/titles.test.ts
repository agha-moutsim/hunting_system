import { describe, expect, it } from "vitest";

import {
  TITLE_MAX_CHARS,
  TITLE_SAMPLE_LIMIT,
  titleLength,
  titleLimitState,
  titleMeterLabel,
  titleMeterPercent,
  titlesPath,
  topTitleTerms,
} from "./titles";

describe("titlesPath", () => {
  it("carries the trimmed query and the limit", () => {
    expect(titlesPath({ q: "  garden hose  ", limit: 50 })).toBe(
      "/api/titles?q=garden+hose&limit=50"
    );
  });

  it("omits the limit when the caller did not set one", () => {
    expect(titlesPath({ q: "garden hose" })).toBe("/api/titles?q=garden+hose");
  });

  it("names the one-page sample ceiling", () => {
    expect(TITLE_SAMPLE_LIMIT).toBe(50);
    expect(titlesPath({ q: "garden hose", limit: TITLE_SAMPLE_LIMIT })).toBe(
      "/api/titles?q=garden+hose&limit=50"
    );
  });

  it("encodes punctuation instead of leaving it in the URL", () => {
    expect(titlesPath({ q: "anti-kink & hose" })).toBe(
      "/api/titles?q=anti-kink+%26+hose"
    );
  });

  it("has no volume parameter to send", () => {
    expect(titlesPath({ q: "garden hose" })).not.toMatch(
      /volume|popularity|rank|score|trend|demand/i
    );
  });
});

describe("titleLength", () => {
  it("counts characters rather than UTF-16 code units", () => {
    expect(titleLength("garden hose")).toBe(11);
    expect(titleLength("🚚")).toBe(1);
  });
});

describe("the 80-character meter", () => {
  it("uses eBay's limit as the denominator", () => {
    expect(TITLE_MAX_CHARS).toBe(80);
    expect(titleMeterLabel(42)).toBe("42 / 80");
  });

  it("is ok at the limit and over past it", () => {
    expect(titleLimitState(80)).toBe("ok");
    expect(titleLimitState(81)).toBe("over");
  });

  it("shows a full bar at the limit and never past 100%", () => {
    expect(titleMeterPercent(40)).toBe(50);
    expect(titleMeterPercent(80)).toBe(100);
    expect(titleMeterPercent(120)).toBe(100);
  });

  it("handles empty and non-finite values without a broken bar", () => {
    expect(titleMeterPercent(0)).toBe(0);
    expect(titleMeterPercent(-5)).toBe(0);
    expect(titleMeterPercent(Number.NaN)).toBe(0);
    expect(titleMeterLabel(Number.NaN)).toBe("0 / 80");
    expect(titleLimitState(Number.NaN)).toBe("ok");
  });
});

describe("topTitleTerms", () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({
    word: `word-${index}`,
    count: 12 - index,
  }));

  it("keeps the server's order and defaults to ten rows", () => {
    expect(topTitleTerms(rows)).toEqual(rows.slice(0, 10));
  });

  it("takes a different limit", () => {
    expect(topTitleTerms(rows, 3)).toEqual(rows.slice(0, 3));
  });

  it("returns nothing for a zero or negative limit", () => {
    expect(topTitleTerms(rows, 0)).toEqual([]);
    expect(topTitleTerms(rows, -1)).toEqual([]);
  });
});
