"use client";

import { TextareaHTMLAttributes } from "react";

export default function Textarea({
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full bg-bg-surface border border-border rounded-control px-3 py-2 text-sm text-white placeholder-text-dim focus:outline-hidden focus:border-accent-blue focus:ring-2 focus:ring-brand-lime/40 min-h-[80px] transition-colors duration-150 ${className}`}
      {...props}
    />
  );
}
