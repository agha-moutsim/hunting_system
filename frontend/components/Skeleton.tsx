"use client";

export function SkeletonLine({ width = "100%" }: { width?: string }) {
  return (
    <div className="skeleton h-4 mb-2" style={{ width }} aria-hidden />
  );
}

export function SkeletonCard() {
  return (
    <div className="skeleton h-24 rounded-xl mb-3" aria-hidden />
  );
}

export function SkeletonChart() {
  return (
    <div className="skeleton h-64 rounded-xl mb-3" aria-hidden />
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-10 rounded-lg mb-2"
          style={{ width: `${100 - i * 4}%` }}
        />
      ))}
    </div>
  );
}

export default function Skeleton({
  lines = 3,
  title = false,
}: {
  lines?: number;
  title?: boolean;
}) {
  return (
    <div aria-hidden>
      {title && <div className="skeleton h-6 w-1/3 mb-3" />}
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonLine key={i} width={i === lines - 1 ? "60%" : "100%"} />
      ))}
    </div>
  );
}
