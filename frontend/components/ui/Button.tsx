"use client";

import { ReactNode, ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const styles: Record<Variant, string> = {
  primary:
    "bg-accent-blue text-white hover:bg-blue-600 disabled:bg-blue-900 disabled:text-blue-400",
  secondary:
    "bg-bg-surface text-text-primary border border-border hover:bg-bg-hover",
  danger:
    "bg-accent-red/10 text-accent-red border border-accent-red/40 hover:bg-accent-red/20",
  ghost:
    "bg-transparent text-text-secondary hover:bg-bg-surface hover:text-text-primary",
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
      className={`px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-60 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
