"use client";

import { SelectHTMLAttributes } from "react";

export default function Select({
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`w-full bg-bg-surface border border-border rounded-control px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-blue focus:ring-2 focus:ring-brand-lime/40 transition-colors duration-150 ${className}`}
      {...props}
    >
      {children}
    </select>
  );
}
