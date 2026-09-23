"use client";

export default function EmptyState({
  icon = "📭",
  title = "Nothing here yet",
  message = "",
  action,
}: {
  icon?: string;
  title?: string;
  message?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="text-center py-12 px-4">
      <div className="text-4xl mb-3 opacity-50">{icon}</div>
      <div className="text-text-primary font-semibold mb-1">{title}</div>
      {message && (
        <div className="text-sm text-text-dim max-w-md mx-auto">{message}</div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
