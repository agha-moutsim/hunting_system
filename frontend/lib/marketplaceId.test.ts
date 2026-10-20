import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_MARKETPLACE_ID,
  MARKETPLACE_HEADER,
  getMarketplaceId,
  marketplaceHeaders,
  setMarketplaceId,
} from "./marketplaceId";

/**
 * The storage layer, not the React hook.
 *
 * The rule worth pinning: with no browser storage (SSR, private mode, a
 * blocked API) the answer is the historical UK default, never an empty market
 * id that a backend would have to guess at.
 */

function installWindow(initial?: string) {
  const values = new Map<string, string>();
  if (initial !== undefined) values.set("ebayhunter.marketplace", initial);
  const dispatchEvent = vi.fn();
  const localStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
  vi.stubGlobal("window", {
    localStorage,
    dispatchEvent,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  vi.stubGlobal(
    "CustomEvent",
    class {
      type: string;
      detail: unknown;
      constructor(type: string, init?: { detail?: unknown }) {
        this.type = type;
        this.detail = init?.detail;
      }
    }
  );
  return { values, dispatchEvent };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getMarketplaceId", () => {
  it("is EBAY_GB when nothing is stored or there is no window", () => {
    expect(getMarketplaceId()).toBe(DEFAULT_MARKETPLACE_ID);
    installWindow();
    expect(getMarketplaceId()).toBe("EBAY_GB");
  });

  it("returns the stored market id", () => {
    installWindow("EBAY_US");
    expect(getMarketplaceId()).toBe("EBAY_US");
  });
});

describe("setMarketplaceId", () => {
  it("persists the id and announces it to mounted surfaces", () => {
    const { values, dispatchEvent } = installWindow();
    setMarketplaceId("EBAY_DE");
    expect(values.get("ebayhunter.marketplace")).toBe("EBAY_DE");
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });
});

describe("marketplaceHeaders", () => {
  it("sends the selected marketplace on every API call", () => {
    installWindow("EBAY_US");
    expect(marketplaceHeaders()).toEqual({
      [MARKETPLACE_HEADER]: "EBAY_US",
    });
  });
});
