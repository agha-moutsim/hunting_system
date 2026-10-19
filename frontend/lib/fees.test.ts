import { describe, expect, it } from "vitest";

import {
  DEFAULT_FEE_FORM,
  buildFeeRequest,
  feeFormFromProfile,
  type FeeFormState,
} from "./fees";

function form(patch: Partial<FeeFormState> = {}): FeeFormState {
  return { ...DEFAULT_FEE_FORM, ...patch };
}

describe("buildFeeRequest - forward mode", () => {
  it("turns the acceptance inputs into the engine's request", () => {
    const built = buildFeeRequest(
      form({
        salePrice: "24.99",
        supplierCost: "9.40",
        postagePaid: "3.20",
        promotedRate: "2",
      })
    );

    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request).toEqual({
      sale_price: 24.99,
      supplier_cost: 9.4,
      postage_charged: 0,
      postage_paid: 3.2,
      category: null,
      promoted_rate: 2,
      seller_type: "business",
      vat_registered: false,
    });
  });

  it("refuses an empty price before the round trip", () => {
    expect(buildFeeRequest(form())).toEqual({
      ok: false,
      error: "Enter a sale price.",
    });
  });

  it("refuses a price of zero with the engine's rule", () => {
    expect(buildFeeRequest(form({ salePrice: "0" }))).toEqual({
      ok: false,
      error: "Sale price must be greater than zero.",
    });
  });

  it("refuses text in a money field", () => {
    const built = buildFeeRequest(form({ salePrice: "twenty" }));

    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error).toContain("number");
  });

  it("keeps a blank supplier as unknown, not zero", () => {
    const built = buildFeeRequest(form({ salePrice: "12.50" }));

    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request.supplier_cost).toBeNull();
  });

  it("sends unpaid postage as the engine's unknown marker", () => {
    const built = buildFeeRequest(form({ salePrice: "12.50" }));

    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request.postage_paid).toBe(0);
  });

  it("keeps a blank category as the stated default", () => {
    const built = buildFeeRequest(form({ salePrice: "12.50" }));

    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request.category).toBeNull();
  });

  it("refuses a negative postage reading", () => {
    const built = buildFeeRequest(
      form({ salePrice: "12.50", postagePaid: "-1" })
    );

    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error).toContain("negative");
  });
});

describe("buildFeeRequest - reverse mode", () => {
  it("asks for the price at a target margin and sends no sale price", () => {
    const built = buildFeeRequest(
      form({
        mode: "reverse",
        targetMargin: "30",
        supplierCost: "9.40",
        postagePaid: "3.20",
        promotedRate: "2",
      })
    );

    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request.target_margin).toBe(30);
    expect(built.request.sale_price).toBeUndefined();
  });

  it("refuses a reverse request without a supplier cost", () => {
    const built = buildFeeRequest(
      form({ mode: "reverse", targetMargin: "30" })
    );

    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error).toContain("Supplier cost");
  });

  it("refuses a target outside the engine's range", () => {
    const built = buildFeeRequest(
      form({ mode: "reverse", targetMargin: "100", supplierCost: "9.40" })
    );

    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error).toContain("below 100");
  });

  it("refuses an empty target", () => {
    const built = buildFeeRequest(
      form({ mode: "reverse", supplierCost: "9.40" })
    );

    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error).toContain("target margin");
  });
});

describe("feeFormFromProfile", () => {
  it("carries the seller settings the pipeline uses", () => {
    const state = feeFormFromProfile({
      seller_type: "private",
      vat_registered: false,
      promoted_rate: 2,
    });

    expect(state.sellerType).toBe("private");
    expect(state.vatRegistered).toBe(false);
    expect(state.promotedRate).toBe("2");
    expect(state.mode).toBe("forward");
  });

  it("leaves an unpromoted seller's rate blank, not '0'", () => {
    const state = feeFormFromProfile({
      seller_type: "business",
      vat_registered: false,
      promoted_rate: 0,
    });

    expect(state.promotedRate).toBe("");
  });
});
