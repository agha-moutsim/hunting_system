"use client";

export default function KpiCard({
  label,
  value,
  delta,
  deltaGood,
}: {
  label: string;
  value: string;
  delta?: string;
  deltaGood?: boolean;
}) {
  return (
    <div className="bg-bg-secondary border border-border rounded-card shadow-card p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-dim mb-1.5">
        {label}
      </div>
      <div className="font-mono text-xl md:text-2xl font-bold text-white tabular-nums">
        {value}
      </div>
      {delta && (
        <div
          className={`text-xs mt-1 font-medium font-mono tabular-nums ${
            deltaGood === undefined
              ? "text-text-dim"
              : deltaGood
                ? "text-brand-lime"
                : "text-accent-red"
          }`}
        >
          {delta}
        </div>
      )}
    </div>
  );
}
