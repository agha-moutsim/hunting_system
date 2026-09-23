"use client";

import { useEffect, useState } from "react";

type Status = {
  db: boolean;
  ollama: boolean;
  ollama_model: string;
  ebay_api: boolean;
};

export default function StatusDots() {
  const [status, setStatus] = useState<Status | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${base}/api/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setChecked(true));
  }, []);

  const dot = (ok: boolean | undefined) => {
    if (!checked || status === null)
      return <span className="text-text-dim">●</span>;
    return ok ? (
      <span className="text-accent-green">●</span>
    ) : (
      <span className="text-accent-amber">●</span>
    );
  };

  return (
    <div className="space-y-1.5 text-xs">
      <div className="text-[10px] uppercase tracking-wider text-text-dim font-semibold">
        System Status
      </div>
      <div className="flex items-center gap-2 text-text-secondary">
        {dot(status?.db)} Database {status?.db ? "" : checked && status ? "" : ""}
        <span className="text-text-dim">
          {!checked ? "…" : status?.db ? "Connected" : "Disconnected"}
        </span>
      </div>
      <div className="flex items-center gap-2 text-text-secondary">
        {dot(status?.ollama)} Ollama{" "}
        <span className="text-text-dim">
          {!checked ? "…" : status?.ollama ? `(${status.ollama_model})` : "Offline"}
        </span>
      </div>
      <div className="flex items-center gap-2 text-text-secondary">
        {dot(status?.ebay_api)} eBay API{" "}
        <span className="text-text-dim">
          {!checked ? "…" : status?.ebay_api ? "Configured" : "Missing keys"}
        </span>
      </div>
    </div>
  );
}
