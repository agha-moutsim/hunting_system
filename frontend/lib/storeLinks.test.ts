import { describe, it, expect } from "vitest";
import { describeStoreLink } from "./storeLinks";

/**
 * REGRESSION-007 — the store link contract, as the UI must render it.
 *
 * The old component stamped every row `Verified` while also drawing a
 * `derived` chip on the same row, because the backend had fabricated a
 * `/str/{username}` storefront URL it never saw. Two contradictory labels on
 * one dead link.
 *
 * The backend now emits `url_kind`, and this module turns that into exactly
 * one honest label. A row may not claim a confirmed storefront unless the
 * link was actually observed on an eBay page.
 */

const OBSERVED = {
  name: "MyBrandShop",
  url: "https://www.ebay.co.uk/str/MyBrandShop",
  url_kind: "observed",
  url_derived: false,
};

const PROFILE = {
  name: "plain_seller_778",
  url: "https://www.ebay.co.uk/usr/plain_seller_778",
  url_kind: "seller_profile",
  url_derived: true,
  provenance: "unverified",
  provenance_reason:
    "storefront URL not confirmed - showing the seller's eBay profile",
};

describe("describeStoreLink", () => {
  it("confirms a storefront only when the /str/ link was observed", () => {
    const view = describeStoreLink(OBSERVED)!;
    expect(view.kind).toBe("observed");
    expect(view.isConfirmedStorefront).toBe(true);
    expect(view.kindLabel).toBe("Store");
  });

  it("labels a profile link as a seller profile, not a store", () => {
    const view = describeStoreLink(PROFILE)!;
    expect(view.kind).toBe("seller_profile");
    expect(view.isConfirmedStorefront).toBe(false);
    expect(view.kindLabel).toBe("Seller profile");
  });

  it("never claims a confirmed storefront for a /usr/ link", () => {
    const view = describeStoreLink(PROFILE)!;
    expect(view.href).toContain("/usr/");
    expect(view.isConfirmedStorefront).toBe(false);
  });

  it("falls back to reading the URL when url_kind is missing (old payloads)", () => {
    // Rows persisted before the change have url_derived but no url_kind.
    const legacy = {
      name: "someone",
      url: "https://www.ebay.co.uk/usr/someone",
      url_derived: true,
    };
    const view = describeStoreLink(legacy)!;
    expect(view.kind).toBe("seller_profile");
    expect(view.isConfirmedStorefront).toBe(false);
  });

  it("treats a legacy /str/ row as observed rather than silently confirmed", () => {
    // A stored /str/ link came from eBay's page, so it is a real storefront
    // href even without the newer field.
    const legacy = {
      name: "s",
      url: "https://www.ebay.co.uk/str/Shop",
      url_derived: false,
    };
    expect(describeStoreLink(legacy)!.isConfirmedStorefront).toBe(true);
  });

  it("returns null for a row with no link so no dead href is rendered", () => {
    expect(describeStoreLink({ name: "no link", url: "" })).toBeNull();
    expect(describeStoreLink({ name: "blank", url: "#" })).toBeNull();
    expect(describeStoreLink({ name: "none", url: undefined })).toBeNull();
  });

  it("refuses to render an http link as a confirmed storefront", () => {
    const hostile = {
      name: "x",
      url: "http://evil.example/str/fake",
      url_kind: "observed",
    };
    const view = describeStoreLink(hostile)!;
    // Off-eBay, so it cannot be presented as a verified eBay storefront.
    expect(view.isConfirmedStorefront).toBe(false);
  });

  it("carries the backend reason through so the UI can explain itself", () => {
    expect(describeStoreLink(PROFILE)!.reason).toContain("storefront");
  });

  it("gives an explanation for the link origin", () => {
    expect(describeStoreLink(OBSERVED)!.explanation).toMatch(/observed/i);
    expect(describeStoreLink(PROFILE)!.explanation).toMatch(/profile/i);
  });
});
