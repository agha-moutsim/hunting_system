/**
 * Phase D - the fee calculator's client plumbing.
 *
 * Nothing here computes a fee. The engine owns the arithmetic and the fee
 * table; this module only shapes form text into the request the API expects
 * and carries the engine's answer back. Form-level refusals (an empty price,
 * a target outside 0-100) happen before the round trip so the user gets the
 * sentence next to the field; every money rule still answers from the engine.
 */

import { apiFetch, apiPost } from "./api";
import type {
  FeeCalculateRequest,
  FeeCalculateResponse,
  FeeTableResponse,
} from "./types";

export function fetchFeeTable(): Promise<FeeTableResponse> {
  return apiFetch<FeeTableResponse>("/api/fees/table");
}

export function calculateFees(
  request: FeeCalculateRequest
): Promise<FeeCalculateResponse> {
  return apiPost<FeeCalculateResponse>("/api/fees/calculate", request);
}

export type FeeMode = "forward" | "reverse";

export interface FeeFormState {
  mode: FeeMode;
  salePrice: string;
  targetMargin: string;
  postageCharged: string;
  postagePaid: string;
  category: string;
  promotedRate: string;
  sellerType: "business" | "private";
  vatRegistered: boolean;
  supplierCost: string;
}

export const DEFAULT_FEE_FORM: FeeFormState = {
  mode: "forward",
  salePrice: "",
  targetMargin: "",
  postageCharged: "0.00",
  postagePaid: "",
  category: "",
  promotedRate: "",
  sellerType: "business",
  vatRegistered: false,
  supplierCost: "",
};

/** The form the seller's profile implies - the same defaults the verdict uses. */
export function feeFormFromProfile(profile: {
  seller_type: string;
  vat_registered: boolean;
  promoted_rate: number;
}): FeeFormState {
  return {
    ...DEFAULT_FEE_FORM,
    sellerType: profile.seller_type === "private" ? "private" : "business",
    vatRegistered: profile.vat_registered,
    promotedRate: profile.promoted_rate > 0 ? `${profile.promoted_rate}` : "",
  };
}

export type FeeRequestBuild =
  { ok: true; request: FeeCalculateRequest } | { ok: false; error: string };

function numberFrom(raw: string): number | null | "invalid" {
  const text = raw.trim();
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : "invalid";
}

/**
 * Form text -> the request body, with the boundaries the engine states.
 *
 * Empty means what the engine says it means: no supplier price (profit is
 * not computed), no category (the stated default), no promoted rate (0%),
 * no postage paid reading (a ceiling, never a zero cost).
 */
export function buildFeeRequest(form: FeeFormState): FeeRequestBuild {
  const salePrice = numberFrom(form.salePrice);
  const targetMargin = numberFrom(form.targetMargin);
  const supplierCost = numberFrom(form.supplierCost);
  const postageCharged = numberFrom(form.postageCharged);
  const postagePaid = numberFrom(form.postagePaid);
  const promotedRate = numberFrom(form.promotedRate);

  if (supplierCost === "invalid") {
    return { ok: false, error: "Supplier cost must be a number." };
  }
  if (supplierCost !== null && supplierCost < 0) {
    return { ok: false, error: "Supplier cost cannot be negative." };
  }
  if (postageCharged === "invalid") {
    return { ok: false, error: "Postage charged must be a number." };
  }
  if (postageCharged !== null && postageCharged < 0) {
    return { ok: false, error: "Postage charged cannot be negative." };
  }
  if (postagePaid === "invalid") {
    return { ok: false, error: "Postage paid must be a number." };
  }
  if (postagePaid !== null && postagePaid < 0) {
    return { ok: false, error: "Postage paid cannot be negative." };
  }
  if (promotedRate === "invalid") {
    return { ok: false, error: "Promoted rate must be a number." };
  }
  if (promotedRate !== null && (promotedRate < 0 || promotedRate >= 100)) {
    return {
      ok: false,
      error: "Promoted rate must be at least 0 and below 100.",
    };
  }

  const common: FeeCalculateRequest = {
    postage_charged: postageCharged ?? 0,
    // 0 is the engine's UNKNOWN marker for the seller's own postage (C1).
    postage_paid: postagePaid ?? 0,
    category: form.category.trim() || null,
    promoted_rate: promotedRate ?? 0,
    seller_type: form.sellerType,
    vat_registered: form.vatRegistered,
    supplier_cost: supplierCost,
  };

  if (form.mode === "reverse") {
    if (targetMargin === "invalid") {
      return { ok: false, error: "Target margin must be a number." };
    }
    if (targetMargin === null) {
      return { ok: false, error: "Enter a target margin to solve for." };
    }
    if (targetMargin < 0 || targetMargin >= 100) {
      return {
        ok: false,
        error: "Target margin must be at least 0 and below 100.",
      };
    }
    if (supplierCost === null) {
      return {
        ok: false,
        error: "Supplier cost is required to solve for a price.",
      };
    }
    return { ok: true, request: { ...common, target_margin: targetMargin } };
  }

  if (salePrice === "invalid") {
    return { ok: false, error: "Sale price must be a number." };
  }
  if (salePrice === null) {
    return { ok: false, error: "Enter a sale price." };
  }
  if (salePrice <= 0) {
    return { ok: false, error: "Sale price must be greater than zero." };
  }
  return { ok: true, request: { ...common, sale_price: salePrice } };
}
