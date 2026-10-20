import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./api";
import {
  EMPTY_SALE_FORM,
  buildSaleRequest,
  changeLabel,
  formatSaleDate,
  monthlyChartData,
  replayThresholds,
  saleDateIsValid,
  salesCsvTemplate,
  tierLabel,
  todayIsoLocal,
} from "./sales";
import type { SalesSummary, ThresholdReplay } from "./types";

vi.mock("./api", () => ({
  apiFetch: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));

function complete(overrides: Partial<typeof EMPTY_SALE_FORM> = {}) {
  return {
    ...EMPTY_SALE_FORM,
    product_name: "Cordless Drill",
    sale_price: "100",
    supplier_cost: "20",
    shipping_cost: "5",
    ebay_fees: "10",
    quantity: "2",
    sale_date: "2026-10-20",
    ...overrides,
  };
}

describe("Phase I sale form", () => {
  it("refuses a blank cost instead of turning it into zero", () => {
    const result = buildSaleRequest(complete({ ebay_fees: "" }));

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/eBay fees is required/i);
  });

  it("accepts a cost the user explicitly states as zero", () => {
    const result = buildSaleRequest(
      complete({ supplier_cost: "0", shipping_cost: "0", ebay_fees: "0" })
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload.supplier_cost).toBe(0);
      expect(result.payload.shipping_cost).toBe(0);
      expect(result.payload.ebay_fees).toBe(0);
    }
  });

  it("sends numbers and keeps the per-unit form values intact", () => {
    const result = buildSaleRequest(complete({ sale_price: "£1,200.50" }));

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload.sale_price).toBe(1200.5);
      expect(result.payload.quantity).toBe(2);
      expect(result.payload.sale_date).toBe("2026-10-20");
    }
  });

  it("refuses a zero quantity, a missing price and an impossible date", () => {
    expect(buildSaleRequest(complete({ quantity: "0" })).ok).toBe(false);
    expect(buildSaleRequest(complete({ sale_price: "" })).ok).toBe(false);
    expect(buildSaleRequest(complete({ sale_date: "2026-02-30" })).ok).toBe(
      false
    );
  });

  it("validates real calendar dates without timezone drift", () => {
    expect(saleDateIsValid("2024-02-29")).toBe(true);
    expect(saleDateIsValid("2025-02-29")).toBe(false);
    expect(formatSaleDate("2026-10-20")).toBe("20 Oct 2026");
  });

  it("starts the date on the browser's local day", () => {
    const now = new Date("2026-10-20T23:30:00");
    expect(todayIsoLocal(now)).toBe("2026-10-20");
  });

  it("builds a CSV template with the current date", () => {
    const template = salesCsvTemplate("2026-10-20");

    expect(template.split("\n")[0]).toContain("supplier_cost");
    expect(template).toContain("2026-10-20");
  });
});

describe("Phase I threshold labels and chart data", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockResolvedValue({} as ThresholdReplay);
  });

  it("asks the backend for current thresholds on first load", async () => {
    await replayThresholds();

    expect(apiFetch).toHaveBeenCalledWith("/api/sales/thresholds");
  });

  it("sends only the thresholds the user proposed", async () => {
    await replayThresholds(0.7, 0.45);

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/sales/thresholds?verified=0.7&unverified=0.45"
    );
  });

  it("keeps an absent monthly profit absent rather than plotting zero", () => {
    const summary = {
      monthly: [
        {
          month: "2026-09",
          label: "Sep 2026",
          revenue: 10,
          profit: null,
          margin: null,
          total_sales: 1,
          total_units: 1,
          profit_is_complete: false,
          profit_missing_reason: "no cost",
        },
        {
          month: "2026-10",
          label: "Oct 2026",
          revenue: 20,
          profit: 5,
          margin: 25,
          total_sales: 1,
          total_units: 1,
          profit_is_complete: true,
          profit_missing_reason: null,
        },
      ],
    } as SalesSummary;

    const chart = monthlyChartData(summary);

    expect(chart.profit).toEqual([null, 5]);
    expect(chart.revenue).toEqual([10, 20]);
  });

  it("names the C14 tiers and every reported change", () => {
    expect(tierLabel("verified")).toBe("Confirmed match");
    expect(tierLabel("unverified")).toBe("Not confirmed");
    expect(tierLabel("no_match")).toBe("No confirmed match");
    expect(changeLabel("verified_to_unverified")).toBe(
      "Confirmed → not confirmed"
    );
  });
});
