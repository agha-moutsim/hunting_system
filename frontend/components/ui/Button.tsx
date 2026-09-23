"use client";

import { ReactNode, ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const styles: Record<Variant, string> = {
  primary:
    "bg-accent-blue text-white hover:bg-accent-blue-dark active:bg-accent-blue-dark disabled:bg-bg-surface disabled:text-text-dim",
  secondary:
    "bg-transparent text-text-primary border border-border hover:bg-bg-surface",
  danger:
    "bg-accent-red/15 text-accent-red border border-accent-red/40 hover:bg-accent-red/25",
  ghost:
    "bg-transparent text-text-secondary hover:bg-bg-surface hover:text-white",
};

export default function Button({
  variant = "primary",
  children,
  className = "",
  ...props
}: {
  variant?: Variant;
  children: ReactNode;
  className?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`px-4 py-2 rounded-control text-sm font-semibold disabled:opacity-60 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-lime ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
