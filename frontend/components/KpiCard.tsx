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
    <div className="bg-bg-secondary border border-border rounded-xl p-4">
      <div className="text-xs text-text-secondary mb-1">{label}</div>
      <div className="text-xl md:text-2xl font-bold text-text-primary">
        {value}
      </div>
      {delta && (
        <div
          className={`text-xs mt-1 font-medium ${
            deltaGood === undefined
              ? "text-text-dim"
              : deltaGood
                ? "text-accent-green"
                : "text-accent-red"
          }`}
        >
          {delta}
        </div>
      )}
    </div>
  );
}
