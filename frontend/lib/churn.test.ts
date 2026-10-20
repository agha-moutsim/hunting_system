import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  NO_LONGER_LISTED_LABEL,
  churnIsClaimable,
  churnPath,
  firstSeenChipLabel,
  firstSeenLabel,
  formatListingPrice,
  lastSeenLabel,
  listingAgeLabel,
  listingObservationPath,
} from "./churn";
import { formatDate } from "./format";
import type { ChurnResponse } from "./types";

const HERE = dirname(fileURLToPath(import.meta.url));

describe("churnPath", () => {
  it("trims the query and encodes it", () => {
    expect(churnPath("  garden hose  ")).toBe(
      "/api/observations/churn?query=garden+hose"
    );
  });

  it("encodes punctuation instead of leaving it in the URL", () => {
    expect(churnPath("anti-kink & hose")).toBe(
      "/api/observations/churn?query=anti-kink+%26+hose"
    );
  });

  it("has no query parameter that could trigger a live search", () => {
    const path = churnPath("garden hose");
    expect(path).not.toContain("search");
    expect(path).not.toContain("limit");
  });
});

describe("listingObservationPath", () => {
  it("encodes the listing id", () => {
    expect(listingObservationPath(" 123/456 ")).toBe(
      "/api/observations/123%2F456"
    );
  });
});

describe("listingAgeLabel", () => {
  it("labels today, one day and many days from measured whole days", () => {
    expect(listingAgeLabel(0)).toBe("LISTED TODAY");
    expect(listingAgeLabel(1)).toBe("LISTED 1 DAY AGO");
    expect(listingAgeLabel(2)).toBe("LISTED 2 DAYS AGO");
    expect(listingAgeLabel(74)).toBe("LISTED 74 DAYS AGO");
  });

  it("floors a fractional day rather than rounding it up", () => {
    expect(listingAgeLabel(2.9)).toBe("LISTED 2 DAYS AGO");
  });

  it("returns null when there is no measured age", () => {
    expect(listingAgeLabel(null)).toBeNull();
    expect(listingAgeLabel(undefined)).toBeNull();
    expect(listingAgeLabel(-1)).toBeNull();
    expect(listingAgeLabel(Number.NaN)).toBeNull();
  });

  it("never uses the completed-sale word", () => {
    const labels = [
      listingAgeLabel(0),
      listingAgeLabel(1),
      listingAgeLabel(74),
      NO_LONGER_LISTED_LABEL,
    ].join(" ");
    expect(labels.toLowerCase()).not.toContain("sold");
  });
});

describe("seen labels", () => {
  const iso = "2026-10-19T12:00:00Z";

  it("labels a last-seen date with its own words", () => {
    expect(lastSeenLabel(iso)).toBe(`Last seen ${formatDate(iso)}`);
  });

  it("labels a first sighting as first seen, not as age", () => {
    expect(firstSeenLabel(iso)).toBe(`First seen here ${formatDate(iso)}`);
    expect(firstSeenChipLabel(iso)).toBe(
      `FIRST SEEN ${formatDate(iso).toUpperCase()}`
    );
  });

  it("has no label when no date was stored", () => {
    expect(lastSeenLabel(null)).toBeNull();
    expect(firstSeenLabel(undefined)).toBeNull();
    expect(firstSeenChipLabel("")).toBeNull();
  });
});

describe("churnIsClaimable", () => {
  const base = { churned: null } as ChurnResponse;

  it("is false while the API is refusing a claim", () => {
    expect(churnIsClaimable(null)).toBe(false);
    expect(churnIsClaimable(base)).toBe(false);
  });

  it("is true for a measured empty comparison", () => {
    expect(churnIsClaimable({ ...base, churned: [] })).toBe(true);
  });

  it("is true when the comparison found a missing listing", () => {
    expect(
      churnIsClaimable({
        ...base,
        churned: [
          {
            listing_id: "1",
            title: "Gone",
            item_url: null,
            price: null,
            currency: null,
            item_creation_date: null,
            first_seen_at: null,
            last_seen_at: null,
          },
        ],
      })
    ).toBe(true);
  });
});

describe("formatListingPrice", () => {
  it("uses the pound sign for GBP", () => {
    expect(formatListingPrice(19.99, "GBP")).toBe("£19.99");
  });

  it("keeps a missing price as an em dash, never zero", () => {
    expect(formatListingPrice(null, "GBP")).toBe("—");
    expect(formatListingPrice(undefined, null)).toBe("—");
  });

  it("shows a different currency's code instead of a pound sign", () => {
    expect(formatListingPrice(12.5, "USD")).toBe("12.50 USD");
  });
});

describe("the copy never says what happened to the listing", () => {
  it("contains no completed-sale word in the page, component or client", () => {
    const files = [
      resolve(HERE, "../app/churn/page.tsx"),
      resolve(HERE, "../components/ListingAge.tsx"),
      resolve(HERE, "./churn.ts"),
    ];
    for (const file of files) {
      expect(readFileSync(file, "utf8").toLowerCase()).not.toContain("sold");
    }
  });
});
