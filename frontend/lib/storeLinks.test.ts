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
  it("recognises a /str/ link as an observed storefront without confirming it", () => {
    // REGRESSION-007: this used to assert isConfirmedStorefront === true for
    // any observed /str/ link. Seeing the href is not confirmation — eBay has
    // to answer — so the claim is now split into observed + confirmed.
    const view = describeStoreLink(OBSERVED)!;
    expect(view.kind).toBe("observed");
    expect(view.isConfirmedStorefront).toBe(false);
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

  it("treats a legacy /str/ row as observed, never as verified on sight", () => {
    // A stored /str/ link came from eBay's page, so it is a real storefront
    // href — but nothing checked that the shop is still there. Stricter than
    // the original contract, which called any observed /str/ link confirmed.
    const legacy = {
      name: "s",
      url: "https://www.ebay.co.uk/str/Shop",
      url_derived: false,
    };
    const view = describeStoreLink(legacy)!;
    expect(view.kind).toBe("observed");
    expect(view.isConfirmedStorefront).toBe(false);
    expect(view.isDeadStore).toBe(false);
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

  it("gives an explanation for the link origin and its certainty", () => {
    // A confirmed store says eBay confirmed it; an unchecked one says so.
    expect(describeStoreLink(CHECKED_VERIFIED)!.explanation).toMatch(
      /confirmed/i
    );
    expect(describeStoreLink(OBSERVED)!.explanation).toMatch(
      /not yet verified/i
    );
    expect(describeStoreLink(PROFILE)!.explanation).toMatch(/profile/i);
  });
});

/**
 * REGRESSION-007, verified half. The backend now CHECKS each observed
 * storefront against eBay and records `store_check`. Measured over eight
 * stores the system had shown as Verified, four came back HTTP 410 - so the
 * UI must be able to say "this shop is not there" and stop offering a link
 * that lands on a dead page.
 */
const CHECKED_VERIFIED = {
  name: "rexgadgets",
  url: "https://www.ebay.co.uk/str/rexgadgets",
  url_kind: "observed",
  store_check: "verified",
};
const CHECKED_DEAD = {
  name: "har_476199",
  url: "https://www.ebay.co.uk/str/har_476199",
  url_kind: "observed",
  store_check: "not_found",
  store_check_reason: "eBay reports no store at this URL",
  provenance: "unverified",
  provenance_reason:
    "eBay reports no storefront at this URL - the seller account is real but the shop is not there",
};
const CHECKED_UNKNOWN = {
  name: "some_store",
  url: "https://www.ebay.co.uk/str/some_store",
  url_kind: "observed",
  store_check: "unavailable",
  store_check_reason: "verification budget spent (12 checks)",
};

describe("describeStoreLink — verified storefronts", () => {
  it("confirms a storefront eBay says exists", () => {
    const v = describeStoreLink(CHECKED_VERIFIED)!;
    expect(v.isConfirmedStorefront).toBe(true);
    expect(v.isDeadStore).toBe(false);
    expect(v.kindLabel).toBe("Store");
    expect(v.href).toBeTruthy();
  });

  it("marks a store eBay denies as dead and gives no link to click", () => {
    const v = describeStoreLink(CHECKED_DEAD)!;
    expect(v.isDeadStore).toBe(true);
    expect(v.isConfirmedStorefront).toBe(false);
    expect(v.kindLabel).toBe("Store not found");
    // A dead shop must not be presented as somewhere to go.
    expect(v.href).toBeNull();
  });

  it("carries the reason eBay gave for the dead store", () => {
    expect(describeStoreLink(CHECKED_DEAD)!.reason).toMatch(/no storefront/i);
  });

  it("does not call an uncheckable store confirmed", () => {
    const v = describeStoreLink(CHECKED_UNKNOWN)!;
    expect(v.isConfirmedStorefront).toBe(false);
    expect(v.isDeadStore).toBe(false);
    expect(v.kindLabel).not.toBe("Store");
  });

  it("still offers a link for a store we could not check", () => {
    // We do not know it is gone, so we may not pretend it is.
    expect(describeStoreLink(CHECKED_UNKNOWN)!.href).toBeTruthy();
    expect(describeStoreLink(CHECKED_UNKNOWN)!.explanation).toMatch(
      /could not|unknown/i
    );
  });

  it("never lets a seller profile claim to be a confirmed storefront", () => {
    const v = describeStoreLink({ ...PROFILE, store_check: "verified" })!;
    expect(v.isConfirmedStorefront).toBe(false);
    expect(v.kindLabel).toBe("Seller profile");
  });

  it("treats an observed row with no check as unconfirmed, not confirmed", () => {
    // An href we happened to see is an OBSERVATION. "Confirmed" now means
    // eBay answered and said the shop is there. This is stricter than the
    // original contract, which called any observed /str/ link confirmed.
    const v = describeStoreLink(OBSERVED)!;
    expect(v.storeCheck).toBeNull();
    expect(v.isConfirmedStorefront).toBe(false);
    expect(v.kindLabel).toBe("Store (unchecked)");
    // Still linkable - we do not know it is gone.
    expect(v.href).toBeTruthy();
  });
});
