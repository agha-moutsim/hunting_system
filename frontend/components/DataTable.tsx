"use client";

import { ReactNode, useState } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
  align?: "left" | "right";
}

export default function DataTable<T>({
  columns,
  rows,
  keyFn,
  emptyMessage = "No rows yet",
}: {
  columns: Column<T>[];
  rows: T[];
  keyFn: (row: T, i: number) => string | number;
  emptyMessage?: string;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  let sorted = [...rows];
  if (sortKey) {
    const col = columns.find((c) => c.key === sortKey);
    if (col?.sortValue) {
      sorted.sort((a, b) => {
        const av = col.sortValue!(a);
        const bv = col.sortValue!(b);
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv));
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
  }

  if (rows.length === 0) {
    return (
      <div className="text-center py-10 text-sm text-text-dim border border-dashed border-border rounded-card">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-border rounded-card bg-bg-secondary shadow-card">
      <table className="w-full text-sm min-w-[640px]">
        <thead>
          <tr className="bg-bg-surface border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-3 py-2.5 text-[11px] font-semibold text-text-dim uppercase tracking-[0.06em] ${
                  col.align === "right" ? "text-right" : "text-left"
                } ${col.sortValue ? "cursor-pointer select-none hover:text-white" : ""}`}
                onClick={() => {
                  if (!col.sortValue) return;
                  if (sortKey === col.key) {
                    setSortDir(sortDir === "asc" ? "desc" : "asc");
                  } else {
                    setSortKey(col.key);
                    setSortDir("asc");
                  }
                }}
              >
                {col.header}
                {sortKey === col.key && (sortDir === "asc" ? " ↑" : " ↓")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={keyFn(row, i)}
              className="border-b border-border last:border-0 hover:bg-bg-surface/60 transition-colors duration-150"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-3 py-2.5 text-white ${
                    col.align === "right"
                      ? "text-right font-mono tabular-nums"
                      : "text-left"
                  }`}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
