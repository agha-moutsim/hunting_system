"use client";

import { TextareaHTMLAttributes } from "react";

export default function Textarea({
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full bg-bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/40 min-h-[80px] ${className}`}
      {...props}
    />
  );
}
