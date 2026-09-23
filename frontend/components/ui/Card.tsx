"use client";

import { ReactNode } from "react";

export default function Card({
  children,
  className = "",
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  action?: ReactNode;
}) {
  return (
    <div
      className={`bg-bg-secondary border border-border rounded-card shadow-card p-4 md:p-5 ${className}`}
    >
      {(title || action) && (
        <div className="flex items-center justify-between mb-3">
          {title && (
            <h3 className="text-sm font-semibold text-white">{title}</h3>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
