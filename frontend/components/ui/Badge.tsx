"use client";

import { ReactNode } from "react";

const tones: Record<string, string> = {
  pass: "bg-emerald-600 text-white",
  fail: "bg-red-600 text-white",
  pending: "bg-amber-600 text-white",
  PASS: "bg-emerald-600 text-white",
  FAIL: "bg-red-600 text-white",
  PENDING: "bg-amber-600 text-white",
  info: "bg-accent-blue/15 text-accent-blue border border-accent-blue/30",
  neutral: "bg-bg-surface text-text-secondary border border-border",
  warn: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
};

export default function Badge({
  tone = "neutral",
  children,
}: {
  tone?: string;
  children: ReactNode;
}) {
  const cls = tones[tone] || tones.neutral;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${cls}`}
    >
      {children}
    </span>
  );
}
