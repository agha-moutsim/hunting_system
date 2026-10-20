import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./api";
import { MARKETPLACE_HEADER } from "./marketplaceId";

/**
 * Phase J's transport rule: the selected marketplace rides on EVERY request,
 * including requests that bring their own headers. Spreading `...options`
 * after the merged headers used to replace them with `options.headers` alone,
 * silently dropping the market on exactly those calls.
 */
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("keeps the marketplace header when the caller sends its own", async () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: () => "EBAY_US",
      },
    });
    const fetchMock = vi.fn(
      async (_url: string, _init: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/test", {
      method: "POST",
      body: JSON.stringify({ query: "widget" }),
      headers: { "X-Test": "1" },
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Test": "1",
      [MARKETPLACE_HEADER]: "EBAY_US",
    });
  });
});
