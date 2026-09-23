"use client";

import Button from "@/components/ui/Button";

export default function ConfirmDialog({
  open,
  title = "Are you sure?",
  message,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title?: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-bg-secondary border border-border rounded-card shadow-elev p-6 max-w-sm w-full text-center">
        <div className="w-10 h-10 mx-auto mb-3 rounded-full bg-accent-red/15 border border-accent-red/40 flex items-center justify-center">
          <span className="text-accent-red font-bold text-lg" aria-hidden>
            !
          </span>
        </div>
        <h3 className="text-white font-semibold mb-2">{title}</h3>
        <p className="text-sm text-text-secondary mb-5">{message}</p>
        <div className="flex gap-3 justify-center">
          <Button variant="danger" onClick={onConfirm}>
            Yes, delete
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
