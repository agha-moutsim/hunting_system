"use client";

import { ReactNode } from "react";

const tones: Record<string, string> = {
  pass: "bg-brand-lime/15 text-brand-lime border border-brand-lime/40",
  PASS: "bg-brand-lime/15 text-brand-lime border border-brand-lime/40",
  fail: "bg-accent-red/15 text-accent-red border border-accent-red/40",
  FAIL: "bg-accent-red/15 text-accent-red border border-accent-red/40",
  pending: "bg-accent-amber/15 text-accent-amber border border-accent-amber/40",
  PENDING: "bg-accent-amber/15 text-accent-amber border border-accent-amber/40",
  info: "bg-accent-blue/30 text-white border border-accent-blue/50",
  neutral: "bg-bg-surface text-text-secondary border border-border",
  warn: "bg-accent-amber/15 text-accent-amber border border-accent-amber/40",
};

export default function Badge({
  tone = "neutral",
  title,
  children,
}: {
  tone?: string;
  title?: string;
  children: ReactNode;
}) {
  const cls = tones[tone] || tones.neutral;
  return (
    <span
      title={title}
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-[0.02em] ${cls}`}
    >
      {children}
    </span>
  );
}
