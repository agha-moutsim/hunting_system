/** Single fetch wrapper for the FastAPI backend. */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Default per-endpoint timeouts (ms). Long ops can override. */
const DEFAULT_TIMEOUT_MS = 60_000;
const TIMEOUT_OVERRIDES: Record<string, number> = {
  "/api/analyze": 180_000,
  "/api/deep-search": 240_000,
  "/api/deep-search/fast": 90_000,
  "/api/bulk": 180_000,
  "/api/hunter/scan": 90_000,
  "/api/hunter/lookup": 120_000,
};

function timeoutFor(path: string): number {
  for (const [prefix, ms] of Object.entries(TIMEOUT_OVERRIDES)) {
    if (path.startsWith(prefix)) return ms;
  }
  return DEFAULT_TIMEOUT_MS;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
  const controller = new AbortController();
  const ms = timeoutFor(path);
  const timer = setTimeout(() => controller.abort(), ms);

  try {
    const res = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      signal: options.signal ?? controller.signal,
      ...options,
    });

    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || body.error || JSON.stringify(body);
      } catch {
        /* keep statusText */
      }
      throw new ApiError(res.status, detail);
    }

    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      const secs = Math.round(ms / 1000);
      throw new ApiError(
        408,
        `Request timed out after ${secs}s. The backend may still be working — check http://localhost:8000/api/status, then retry.`
      );
    }
    if (err instanceof TypeError && /fetch/i.test(err.message)) {
      throw new ApiError(
        0,
        "Cannot reach the backend at " +
          BASE +
          ". Is the API running? (cd backend && python -m uvicorn main:app --port 8000)"
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** POST JSON helper. */
export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** PUT JSON helper. */
export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** DELETE helper. */
export function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}

/** Download a file from GET or POST endpoint. */
export async function downloadFile(
  path: string,
  filename: string,
  method: "GET" | "POST" = "GET",
  body?: unknown
): Promise<void> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, "Download failed");

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition");
  let name = filename;
  const match = disposition && disposition.match(/filename="?([^"]+)"?/);
  if (match) name = match[1];

  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

export const API_BASE = BASE;
