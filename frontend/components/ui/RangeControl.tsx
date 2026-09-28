"use client";

import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Input, { Label } from "@/components/ui/Input";
import { apiFetch, apiPut } from "@/lib/api";
import { FiltersResponse, PriceRange, RangeUpdateResponse } from "@/lib/types";

export default function RangeControl({
  onApplied,
  className = "",
}: {
  onApplied?: (range: PriceRange) => void;
  className?: string;
}) {
  const [range, setRange] = useState<PriceRange | null>(null);
  const [defaults, setDefaults] = useState<{
    price_min: number;
    price_max: number;
  } | null>(null);
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<FiltersResponse>("/api/filters");
        if (cancelled) return;
        setRange(data.range);
        setDefaults(data.defaults);
        setMin(String(data.range.min));
        setMax(String(data.range.max));
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not load the price range"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function put(body: { price_min: number; price_max: number }) {
    setSaving(true);
    setError(null);
    try {
      const data = await apiPut<RangeUpdateResponse>("/api/filters", body);
      setRange(data.range);
      setMin(String(data.range.min));
      setMax(String(data.range.max));
      onApplied?.(data.range);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update the price range"
      );
    } finally {
      setSaving(false);
    }
  }

  function apply() {
    if (saving) return;
    const lo = parseFloat(min);
    const hi = parseFloat(max);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
      setError("Enter a numeric min and max.");
      return;
    }
    put({ price_min: lo, price_max: hi });
  }

  function reset() {
    if (saving || !defaults) return;
    put({ price_min: defaults.price_min, price_max: defaults.price_max });
  }

  return (
    <div
      className={`bg-bg-primary border border-border rounded-card p-4 ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="text-sm font-semibold text-white">Price range</div>
        <span className="text-xs font-mono tabular-nums text-text-secondary">
          Active {range ? `£${range.min}–£${range.max}` : "…"}
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-28">
          <Label htmlFor="range-min">Min (£)</Label>
          <Input
            id="range-min"
            type="number"
            min="0"
            step="0.01"
            value={min}
            onChange={(e) => setMin(e.target.value)}
            disabled={loading || saving}
            className="font-mono tabular-nums"
          />
        </div>
        <div className="w-28">
          <Label htmlFor="range-max">Max (£)</Label>
          <Input
            id="range-max"
            type="number"
            min="0"
            step="0.01"
            value={max}
            onChange={(e) => setMax(e.target.value)}
            disabled={loading || saving}
            className="font-mono tabular-nums"
          />
        </div>
        <Button
          type="button"
          onClick={apply}
          disabled={loading || saving}
          className="sm:w-24 justify-center"
        >
          {saving ? "Saving…" : "Apply"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={reset}
          disabled={loading || saving || !defaults}
        >
          Reset to defaults
        </Button>
      </div>

      <p className="text-xs text-text-dim mt-2">
        Applies everywhere: default views show rows inside this range; supplier
        prices are never gated.
      </p>

      {error && <p className="text-xs text-accent-red mt-2">⚠️ {error}</p>}
    </div>
  );
}
