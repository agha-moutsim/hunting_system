"use client";

export default function Spinner({
  label = "Loading...",
  size = "md",
}: {
  label?: string;
  size?: "sm" | "md" | "lg";
}) {
  const dims = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-8 w-8" };
  return (
    <div className="flex items-center gap-3 text-text-secondary">
      <div
        className={`${dims[size]} border-2 border-border border-t-brand-lime rounded-full animate-spin`}
      />
      <span className="text-sm">{label}</span>
    </div>
  );
}
