import { describe, expect, it } from "vitest";

import { bulkCsv } from "./bulkCsv";

const ROW = {
  product_name: "Widget",
  product_category: "Gadgets",
  verdict: "pass",
  ebay_avg_price: 24.99,
  best_supplier_price: 9.99,
  profit: 5.5,
  margin: 22,
  profit_computed: true,
  ebay_total_sold_30d: 40,
};

describe("bulkCsv", () => {
  it("exports measured figures as plain numbers", () => {
    const [, cells] = bulkCsv([ROW]).split("\n");
    expect(cells).toBe("Widget,Gadgets,pass,24.99,9.99,5.50,22.0,40");
  });

  it("leaves unread money and counts blank, never zero", () => {
    const [, cells] = bulkCsv([
      {
        ...ROW,
        ebay_avg_price: 0,
        best_supplier_price: null,
        profit: 0,
        margin: 0,
        profit_computed: false,
        ebay_total_sold_30d: 0,
      },
    ]).split("\n");
    expect(cells).toBe("Widget,Gadgets,pass,,,,,");
  });

  it("keeps a measured break-even as a real zero", () => {
    const [, cells] = bulkCsv([
      { ...ROW, profit: 0, margin: 0, profit_computed: true },
    ]).split("\n");
    expect(cells).toBe("Widget,Gadgets,pass,24.99,9.99,0.00,0.0,40");
  });

  it("does not price a row whose profit was never computed", () => {
    const [, cells] = bulkCsv([
      { ...ROW, profit: 7.5, margin: 30, profit_computed: false },
    ]).split("\n");
    expect(cells).toBe("Widget,Gadgets,pass,24.99,9.99,,,40");
  });

  it("quotes commas and quotes so columns do not shift", () => {
    const [, cells] = bulkCsv([
      { ...ROW, product_name: 'Widget, "large"' },
    ]).split("\n");
    expect(cells.startsWith('"Widget, ""large"""')).toBe(true);
  });
});
