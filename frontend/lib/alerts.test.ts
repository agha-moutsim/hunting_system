import { describe, expect, it } from "vitest";

import {
  ALERT_TABS,
  alertTypeLabel,
  alertUnit,
  alertsPath,
  formatAlertPair,
  formatAlertValue,
  unreadAlerts,
  unreadBadge,
} from "./alerts";
import type { PriceAlert } from "./types";

function alert(patch: Partial<PriceAlert> = {}): PriceAlert {
  return {
    id: 1,
    product_id: 1,
    product_name: "cordless drill",
    alert_type: "price_drop",
    message: "cordless drill item price dropped from £18.99 to £15.49",
    old_price: 18.99,
    new_price: 15.49,
    is_read: false,
    created_at: "2026-10-20T01:00:00",
    ...patch,
  };
}

describe("alertsPath", () => {
  it("asks for everything when no filter is given", () => {
    expect(alertsPath()).toBe("/api/alerts");
  });

  it("carries the unread filter and paging", () => {
    expect(alertsPath({ unreadOnly: true, limit: 20, offset: 40 })).toBe(
      "/api/alerts?unread_only=true&limit=20&offset=40"
    );
  });

  it("keeps a comma-separated type list as one value", () => {
    expect(alertsPath({ alertType: "price_drop,price_increase" })).toBe(
      "/api/alerts?alert_type=price_drop%2Cprice_increase"
    );
  });

  it("omits an empty type filter rather than asking for nothing", () => {
    expect(alertsPath({ alertType: "" })).toBe("/api/alerts");
  });
});

describe("ALERT_TABS", () => {
  it("matches the design: All, Price, Margin, New matches", () => {
    expect(ALERT_TABS.map((tab) => tab.label)).toEqual([
      "All",
      "Price",
      "Margin",
      "New matches",
    ]);
  });

  it("sends Price asks for both directions and target hits", () => {
    const price = ALERT_TABS.find((tab) => tab.key === "price");
    expect(price?.alertType?.split(",")).toEqual([
      "price_drop",
      "price_increase",
      "target_hit",
    ]);
  });

  it("marks only the New matches tab as reading the other lane", () => {
    const matches = ALERT_TABS.filter((tab) => tab.readsMatches);
    expect(matches.map((tab) => tab.key)).toEqual(["matches"]);
  });
});

describe("the unit is the row's, never a guess", () => {
  it("prices are money", () => {
    expect(alertUnit("price_drop")).toBe("price");
    expect(alertUnit("target_hit")).toBe("price");
  });

  it("margin rows are percentages", () => {
    expect(alertUnit("margin_alert")).toBe("margin");
  });

  it("formats a margin row as two percentages", () => {
    expect(
      formatAlertPair({
        alert_type: "margin_alert",
        old_price: 33.5,
        new_price: 22.9,
      })
    ).toBe("33.5% → 22.9%");
  });

  it("formats a price row as two pounds values", () => {
    expect(formatAlertPair(alert())).toBe("£18.99 → £15.49");
  });

  it("a missing value is a dash, not a zero", () => {
    expect(formatAlertValue(null, "price")).toBe("—");
    expect(formatAlertValue(undefined, "margin")).toBe("—");
    expect(formatAlertValue(Number.NaN, "price")).toBe("—");
  });
});

describe("alertTypeLabel", () => {
  it("names each type the app writes", () => {
    expect(alertTypeLabel("price_drop")).toBe("Price drop");
    expect(alertTypeLabel("price_increase")).toBe("Price rise");
    expect(alertTypeLabel("target_hit")).toBe("Target hit");
    expect(alertTypeLabel("margin_alert")).toBe("Margin");
  });

  it("falls back to a neutral label for an unknown type", () => {
    expect(alertTypeLabel("something_new")).toBe("Alert");
  });
});

describe("the sidebar badge", () => {
  it("is absent at zero and for nonsense", () => {
    expect(unreadBadge(0)).toBeNull();
    expect(unreadBadge(-1)).toBeNull();
    expect(unreadBadge(Number.NaN)).toBeNull();
  });

  it("shows small counts as they are", () => {
    expect(unreadBadge(3)).toBe("3");
    expect(unreadBadge(99)).toBe("99");
  });

  it("caps so it cannot stretch the nav", () => {
    expect(unreadBadge(120)).toBe("99+");
  });
});

describe("unreadAlerts", () => {
  it("keeps only the rows that still need attention", () => {
    const rows = [alert({ id: 1 }), alert({ id: 2, is_read: true })];

    expect(unreadAlerts(rows).map((row) => row.id)).toEqual([1]);
  });
});
