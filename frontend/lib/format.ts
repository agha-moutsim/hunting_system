/** Display formatters. */

const CURRENCY_SYMBOLS: Record<string, string> = {
  GBP: "£",
  USD: "$",
  EUR: "€",
  AUD: "A$",
  CAD: "C$",
};

/**
 * One amount in its own currency. Never converts and never adds two
 * currencies: an unrecognised code is spelled out beside the number rather
 * than dressed in a symbol it does not own.
 */
export function formatMoney(
  n: number | null | undefined,
  currency = "GBP"
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const code = (currency || "GBP").toUpperCase();
  const symbol = CURRENCY_SYMBOLS[code];
  return symbol ? `${symbol}${n.toFixed(2)}` : `${n.toFixed(2)} ${code}`;
}

export function currencySymbol(currency = "GBP"): string {
  const code = (currency || "GBP").toUpperCase();
  return CURRENCY_SYMBOLS[code] || code;
}

export function formatGBP(n: number | null | undefined): string {
  return formatMoney(n, "GBP");
}

export function formatGBPCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1000) return `£${(n / 1000).toFixed(1)}k`;
  return `£${n.toFixed(2)}`;
}

export function formatPercent(
  n: number | null | undefined,
  digits = 1
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

export function formatSigned(
  n: number | null | undefined,
  suffix = "%"
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}${suffix}`;
}

export function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Truncate long titles for list views. */
export function truncate(s: string, max = 60): string {
  if (!s) return "";
  return s.length > max ? `${s.slice(0, max - 3)}...` : s;
}

/**
 * A stored timestamp as the instant it actually is.
 *
 * Every timestamp this app stores is naive UTC — that is what SQLite hands
 * back — and `new Date("2026-10-19T19:15:00")` reads a zone-less string as
 * LOCAL time. On a machine five hours off UTC that is a five-hour lie about
 * when something was observed. The repo's rule is that a zone-less value is
 * UTC; it lives here once so every caller applies the same one.
 */
export function asUtc(iso: string): number {
  if (!iso) return NaN;
  const hasZone = /([Zz]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`).getTime();
}

/** How long ago, given a timestamp that may be naive UTC. "never" if unusable. */
export function timeAgo(iso: string): string {
  const then = asUtc(iso);
  if (!Number.isFinite(then)) return "never";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * The instant a figure was OBSERVED, printed in UTC with the zone named.
 *
 * Deliberately not `formatDateTime`: that formats in the browser's own zone and
 * prints none, so a capture read at 19:15 UTC would render as 00:15 on a screen
 * five hours ahead and read as a different fact from the one stored.
 * Provenance is the one place where the zone is part of the claim, so it is
 * printed rather than assumed.
 */
export function formatObservedAt(iso?: string | null): string {
  if (!iso) return "\u2014";
  const at = asUtc(iso);
  if (!Number.isFinite(at)) return "\u2014";
  const stamp = new Date(at).toLocaleString("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${stamp} UTC`;
}
