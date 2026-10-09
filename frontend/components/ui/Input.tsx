"use client";

import { InputHTMLAttributes, LabelHTMLAttributes, ReactNode } from "react";

export function Label({
  children,
  ...props
}: { children: ReactNode } & LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className="block text-xs font-medium text-text-secondary mb-1"
      {...props}
    >
      {children}
    </label>
  );
}

export default function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full bg-bg-surface border border-border rounded-control px-3 py-2 text-sm text-white placeholder-text-dim focus:outline-hidden focus:border-accent-blue focus:ring-2 focus:ring-brand-lime/40 transition-colors duration-150 ${className}`}
      {...props}
    />
  );
}
