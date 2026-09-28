"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Input, { Label } from "@/components/ui/Input";
import { PriceRange } from "@/lib/types";

export default function RangeFilterBar({
  initial,
  onApply,
  onReset,
  loading = false,
  className = "",
}: {
  initial?: PriceRange | null;
  onApply: (min: number, max: number) => void;
  onReset: () => void;
  loading?: boolean;
  className?: string;
}) {
  const initMin = initial?.min;
  const initMax = initial?.max;
  const [min, setMin] = useState(initMin != null ? String(initMin) : "");
  const [max, setMax] = useState(initMax != null ? String(initMax) : "");

  useEffect(() => {
    if (initMin != null) setMin(String(initMin));
    if (initMax != null) setMax(String(initMax));
  }, [initMin, initMax]);

  function apply() {
    if (loading) return;
    const lo = parseFloat(min);
    const hi = parseFloat(max);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return;
    onApply(lo, hi);
  }

  function reset() {
    if (loading) return;
    onReset();
  }

  return (
    <div className={`flex flex-wrap items-end gap-3 ${className}`}>
      <div className="w-24">
        <Label htmlFor="view-price-min">Min (£)</Label>
        <Input
          id="view-price-min"
          type="number"
          min="0"
          step="0.01"
          value={min}
          onChange={(e) => setMin(e.target.value)}
          disabled={loading}
          className="font-mono tabular-nums"
        />
      </div>
      <div className="w-24">
        <Label htmlFor="view-price-max">Max (£)</Label>
        <Input
          id="view-price-max"
          type="number"
          min="0"
          step="0.01"
          value={max}
          onChange={(e) => setMax(e.target.value)}
          disabled={loading}
          className="font-mono tabular-nums"
        />
      </div>
      <Button
        type="button"
        onClick={apply}
        disabled={loading}
        className="justify-center"
      >
        Apply
      </Button>
      <Button type="button" variant="ghost" onClick={reset} disabled={loading}>
        Reset
      </Button>
      <span className="text-xs text-text-dim pb-2">
        This view only — Reset restores the active range
      </span>
      <Link
        href="/analyze"
        title="Change the active price range on the Analyze page"
      >
        <Badge tone="info">
          Active £{initMin ?? "…"}–£{initMax ?? "…"}
        </Badge>
      </Link>
    </div>
  );
}
