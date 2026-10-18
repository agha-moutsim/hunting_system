import { describe, it, expect } from "vitest";

// extension/background.js imports these exact functions as an ES module, so the
// rules that protect a signed-in eBay account are covered here rather than by
// hope. The two that matter most are the per-item dedupe window and the
// absolute hourly cap: a rate limiter nobody tests is a rate limiter that has
// quietly stopped working.
import {
  DEDUPE_MS,
  EMPTY_STATE,
  MAX_PER_HOUR,
  decideCapture,
  describeSkip,
  extractItemId,
  localDayKey,
  noteAttempt,
  noteResult,
  noteStored,
  rollWindows,
} from "../../extension/logic.js";

/** Mirrors the CaptureState typedef in extension/logic.js. */
type CaptureState = {
  quiet: boolean;
  lastCaptured: Record<string, number>;
  hourWindowStart: number;
  hourCount: number;
  dayKey: string;
  dayCount: number;
  lastCaptureAt: number | null;
  lastResult: { ok: boolean; message: string } | null;
};

const NOW = Date.UTC(2026, 0, 15, 12, 0, 0);

function state(overrides: Partial<CaptureState> = {}): CaptureState {
  return {
    quiet: false,
    lastCaptured: {},
    hourWindowStart: NOW,
    hourCount: 0,
    dayKey: localDayKey(NOW),
    dayCount: 0,
    lastCaptureAt: null,
    lastResult: null,
    ...overrides,
  };
}

describe("extractItemId", () => {
  it("reads the item id from the slugged listing URL eBay serves", () => {
    expect(
      extractItemId("https://www.ebay.co.uk/itm/great-widget/1234567890")
    ).toBe("1234567890");
  });

  it("reads a bare listing URL carrying tracking parameters", () => {
    expect(
      extractItemId("https://www.ebay.co.uk/itm/1234567890?ul_redir=true")
    ).toBe("1234567890");
  });

  it("reads the item= parameter, which is the purchase-history shape", () => {
    expect(
      extractItemId(
        "https://www.ebay.co.uk/bin/purchaseHistory?item=1234567890"
      )
    ).toBe("1234567890");
  });

  it("returns null for a search page, so nothing is captured off a listing", () => {
    expect(
      extractItemId("https://www.ebay.co.uk/sch/i.html?_nkw=widget")
    ).toBeNull();
  });

  it("returns null for missing input rather than guessing an id", () => {
    expect(extractItemId("")).toBeNull();
    expect(extractItemId(null)).toBeNull();
    expect(extractItemId(undefined)).toBeNull();
  });
});

describe("decideCapture", () => {
  it("captures an item that has not been seen", () => {
    const decision = decideCapture({ itemId: "111", now: NOW, state: state() });
    expect(decision).toEqual({ capture: true, reason: "ok" });
  });

  it("refuses to guess when there is no item id", () => {
    const decision = decideCapture({ itemId: null, now: NOW, state: state() });
    expect(decision.capture).toBe(false);
    expect(decision.reason).toBe("not-an-item-page");
  });

  it("captures nothing at all in quiet mode - not even when forced", () => {
    const quiet = state({ quiet: true });
    expect(
      decideCapture({ itemId: "111", now: NOW, state: quiet }).reason
    ).toBe("quiet");
    expect(
      decideCapture({ itemId: "111", now: NOW, state: quiet, force: true })
        .reason
    ).toBe("quiet");
  });

  it("holds the hourly cap even against an explicit request", () => {
    const capped = state({ hourCount: MAX_PER_HOUR });
    expect(
      decideCapture({ itemId: "111", now: NOW, state: capped }).reason
    ).toBe("hourly-cap");
    expect(
      decideCapture({ itemId: "111", now: NOW, state: capped, force: true })
        .reason
    ).toBe("hourly-cap");
  });

  it("refuses an item captured inside the dedupe window", () => {
    const recent = state({ lastCaptured: { "111": NOW - DEDUPE_MS + 1 } });
    expect(
      decideCapture({ itemId: "111", now: NOW, state: recent }).reason
    ).toBe("recently-captured");
  });

  it("allows the same item again once the window has passed", () => {
    const old = state({ lastCaptured: { "111": NOW - DEDUPE_MS } });
    expect(decideCapture({ itemId: "111", now: NOW, state: old }).capture).toBe(
      true
    );
  });

  it("lets an explicit request override the dedupe window but nothing else", () => {
    const recent = state({ lastCaptured: { "111": NOW - 1000 } });
    expect(
      decideCapture({ itemId: "111", now: NOW, state: recent, force: true })
        .capture
    ).toBe(true);
  });

  it("keys the window per item, so one capture does not block another", () => {
    const seen = state({ lastCaptured: { "111": NOW - 1000 } });
    expect(
      decideCapture({ itemId: "222", now: NOW, state: seen }).capture
    ).toBe(true);
  });

  it("keeps the account-safety limits inside sane bounds", () => {
    expect(DEDUPE_MS).toBeGreaterThanOrEqual(60 * 60 * 1000);
    expect(MAX_PER_HOUR).toBeGreaterThan(0);
    expect(MAX_PER_HOUR).toBeLessThanOrEqual(120);
  });
});

describe("rollWindows", () => {
  it("resets the request counter once the hour window has expired", () => {
    const rolled = rollWindows(state({ hourCount: 12 }), NOW + 60 * 60 * 1000);
    expect(rolled.hourCount).toBe(0);
    expect(rolled.hourWindowStart).toBe(NOW + 60 * 60 * 1000);
  });

  it("leaves the counter alone inside the hour", () => {
    const rolled = rollWindows(state({ hourCount: 12 }), NOW + 60 * 1000);
    expect(rolled.hourCount).toBe(12);
    expect(rolled.hourWindowStart).toBe(NOW);
  });

  it("resets the stored-capture count on a new local day", () => {
    const rolled = rollWindows(
      state({ dayCount: 7, dayKey: "2026-01-15" }),
      Date.UTC(2026, 0, 16, 12, 0, 0)
    );
    expect(rolled.dayCount).toBe(0);
    expect(rolled.dayKey).toBe(localDayKey(Date.UTC(2026, 0, 16, 12, 0, 0)));
  });

  it("never mutates the state it was handed", () => {
    const before = state({ hourCount: 3, dayCount: 2 });
    const snapshot = JSON.parse(JSON.stringify(before));
    rollWindows(before, NOW + 90 * 60 * 1000);
    expect(before).toEqual(snapshot);
  });
});

describe("noteAttempt", () => {
  it("marks the item and counts the request without counting a stored capture", () => {
    const next = noteAttempt(state(), { itemId: "111", now: NOW });
    expect(next.lastCaptured["111"]).toBe(NOW);
    expect(next.hourCount).toBe(1);
    expect(next.lastCaptureAt).toBe(NOW);
    // An attempt is not a row: the badge must not move until the backend says so.
    expect(next.dayCount).toBe(0);
  });

  it("never mutates the state it was handed", () => {
    const before = state();
    const snapshot = JSON.parse(JSON.stringify(before));
    noteAttempt(before, { itemId: "111", now: NOW });
    expect(before).toEqual(snapshot);
    expect(before.lastCaptured).toEqual({});
  });
});

describe("noteStored", () => {
  it("counts only a capture the backend acknowledged", () => {
    expect(noteStored(state({ dayCount: 4 })).dayCount).toBe(5);
  });
});

describe("noteResult", () => {
  it("keeps the backend's own words for the popup", () => {
    const next = noteResult(state(), { ok: false, message: "HTTP 403" });
    expect(next.lastResult).toEqual({ ok: false, message: "HTTP 403" });
  });

  it("coerces a non-boolean outcome rather than storing a truthy string", () => {
    const next = noteResult(state(), { ok: "yes", message: "thing" });
    expect(next.lastResult).toEqual({ ok: true, message: "thing" });
  });
});

describe("describeSkip", () => {
  it("gives the user a sentence for every reason the capture can be skipped", () => {
    for (const reason of [
      "not-an-item-page",
      "quiet",
      "recently-captured",
      "hourly-cap",
    ]) {
      const text = describeSkip(reason);
      expect(typeof text).toBe("string");
      expect(text.length).toBeGreaterThan(0);
      expect(text).not.toBe(reason);
    }
  });

  it("states the actual cap in the cap message", () => {
    expect(describeSkip("hourly-cap")).toContain(String(MAX_PER_HOUR));
  });

  it("passes an unknown code through instead of inventing a sentence", () => {
    expect(describeSkip("something-new")).toBe("something-new");
  });
});

describe("localDayKey", () => {
  it("formats a local calendar day as YYYY-MM-DD", () => {
    expect(localDayKey(Date.UTC(2026, 0, 5, 12, 0, 0))).toMatch(
      /^\d{4}-\d{2}-\d{2}$/
    );
  });

  it("changes at the local day boundary, which is what resets the badge", () => {
    const a = localDayKey(Date.UTC(2026, 0, 15, 12, 0, 0));
    const b = localDayKey(Date.UTC(2026, 0, 16, 12, 0, 0));
    expect(a).not.toBe(b);
  });
});

describe("EMPTY_STATE", () => {
  it("starts capturing, with nothing counted yet", () => {
    expect(EMPTY_STATE.quiet).toBe(false);
    expect(EMPTY_STATE.hourCount).toBe(0);
    expect(EMPTY_STATE.dayCount).toBe(0);
    expect(EMPTY_STATE.lastCaptureAt).toBeNull();
  });
});
