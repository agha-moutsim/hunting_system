"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import Spinner from "@/components/Spinner";
import { apiFetch } from "@/lib/api";
import { DealItem, DealsMeta, DealsResponse } from "@/lib/types";
import { describeStoreLink } from "@/lib/storeLinks";

/**
 * How many cards are on screen at once, and how often the window moves on.
 *
 * The rotation is a DISPLAY concern only. Everything it shows is already
 * stored: the pool is fetched by a scheduled job (about 73 Browse calls, which
 * is why it cannot happen on a page view). Rotating reveals more of what was
 * already collected and picks up newer data on the next tick; it does not, and
 * must not, imply these are the best-selling items. Nothing here knows which
 * products sell best, because eBay does not publish that to this app.
 */
const WINDOW = 8;
const ROTATE_MS = 60_000;

/**
 * Read a backend timestamp as the instant it actually is.
 *
 * `backend/hunter/deals.py` stores naive UTC, so the API hands back a bare
 * "2026-10-19T00:20:00" with no zone. `new Date()` parses that as LOCAL time,
 * which made a board refreshed seconds earlier read "updated 5h ago" on a
 * UTC+5 machine while the server's own `stale` flag said it was current — the
 * page contradicting itself about the same row. Marking it UTC unless it
 * already carries a zone is what makes the two agree.
 */
function asUtc(iso: string): number {
  if (!iso) return NaN;
  const hasZone = /([Zz]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`).getTime();
}

function timeAgo(iso: string): string {
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

function DealCard({ item }: { item: DealItem }) {
  // The shared store ladder decides what this link is, so a deal cannot label
  // itself differently from every other seller row in the app. A `/usr/` URL is
  // a seller profile and is called one; only an eBay-rendered `/str/` link
  // would ever be shown as a storefront.
  const store = describeStoreLink({
    name: item.store_name || item.seller,
    url: item.store_url,
  });
  const sellerName = item.store_name || item.seller;

  return (
    <div className="group bg-bg-secondary border border-border rounded-card overflow-hidden flex flex-col transition-all duration-200 hover:border-brand-lime/50 hover:shadow-card">
      <a
        href={item.item_url}
        target="_blank"
        rel="noopener noreferrer"
        className="relative block focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-lime"
        aria-label={`Open ${item.title} on eBay`}
      >
        {/* eBay listing images are shot on white, so the tile is white and the
            image is contained rather than cropped — cropping a product shot
            cuts the product. */}
        <div className="aspect-[4/3] bg-white flex items-center justify-center p-3">
          {item.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.image_url}
              alt=""
              loading="lazy"
              className="max-h-full max-w-full object-contain transition-transform duration-300 group-hover:scale-[1.04]"
            />
          ) : (
            <span className="text-xs text-bg-sidebar/50">no image</span>
          )}
        </div>
        {item.condition && (
          <span className="absolute top-2 left-2 text-[10px] font-semibold uppercase tracking-[0.04em] bg-bg-sidebar/85 text-text-secondary px-2 py-0.5 rounded-full backdrop-blur-sm">
            {item.condition}
          </span>
        )}
      </a>

      <div className="p-3 flex flex-col gap-2 flex-1 min-w-0">
        <a
          href={item.item_url}
          target="_blank"
          rel="noopener noreferrer"
          title={item.title}
          className="text-sm font-medium text-text-primary leading-snug line-clamp-2 hover:text-brand-lime transition-colors duration-150"
        >
          {item.title}
        </a>

        <div className="mt-auto pt-1 space-y-2">
          {item.price_read ? (
            <div className="font-mono tabular-nums text-lg font-bold text-brand-lime leading-none">
              {item.price_label}
            </div>
          ) : (
            // Not read is not the same as free. A number here would be a claim
            // nobody measured, so the card says where to find the real one.
            <div className="text-xs text-text-dim">
              See price on eBay
              <span className="sr-only">
                {" "}
                — the price for this listing was not read
              </span>
            </div>
          )}

          {store && sellerName && (
            <a
              href={store.href ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              title={store.explanation}
              className="flex items-center gap-1.5 text-xs text-text-dim hover:text-text-secondary transition-colors duration-150 min-w-0"
            >
              <span className="truncate">{sellerName}</span>
              <span className="shrink-0 text-[10px] uppercase tracking-[0.04em] text-text-dim/70">
                {store.kindLabel}
              </span>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

export default function DealsBoard() {
  const [pool, setPool] = useState<DealItem[]>([]);
  const [meta, setMeta] = useState<DealsMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [paused, setPaused] = useState(false);
  const [offset, setOffset] = useState(0);
  const [cycleStart, setCycleStart] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const d = await apiFetch<DealsResponse>("/api/deals");
      setPool(d.items || []);
      setMeta(d.meta || null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load deals");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // A one-second display clock. Separate from the rotation timer so the
  // countdown can freeze when paused without stopping the clock itself.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // The rotation. Advances the window through the pool it already has, and
  // re-reads so the next tick can show data that arrived since the last one.
  useEffect(() => {
    if (loading || paused || pool.length === 0) return;
    const t = setInterval(() => {
      setOffset((o) => o + WINDOW);
      setCycleStart(Date.now());
      load();
    }, ROTATE_MS);
    return () => clearInterval(t);
  }, [loading, paused, pool.length, load]);

  const visible = useMemo(() => {
    if (pool.length === 0) return [];
    const start = offset % pool.length;
    const count = Math.min(WINDOW, pool.length);
    const out: DealItem[] = [];
    for (let i = 0; i < count; i += 1) {
      out.push(pool[(start + i) % pool.length]);
    }
    return out;
  }, [pool, offset]);

  const elapsed = Math.min(ROTATE_MS, Math.max(0, now - cycleStart));
  const progress =
    paused || pool.length === 0 ? 0 : (elapsed / ROTATE_MS) * 100;
  const remaining = Math.max(0, Math.ceil((ROTATE_MS - elapsed) / 1000));

  function togglePause() {
    setPaused((p) => {
      if (!p) return true;
      setCycleStart(Date.now()); // resume with a full cycle
      return false;
    });
  }

  /**
   * Ask the backend to refresh now, then poll until the new pool lands.
   *
   * The request that starts the refresh returns immediately — it is the same
   * endpoint the page already uses, with a flag — because waiting on ~73 eBay
   * calls inside one HTTP request is exactly what this design avoids.
   */
  async function fetchNow() {
    if (busy) return;
    setBusy(true);
    try {
      const started = await apiFetch<DealsResponse>("/api/deals?refresh=true");
      setMeta(started.meta || null);
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await new Promise((r) => setTimeout(r, 3000));
        const d = await apiFetch<DealsResponse>("/api/deals");
        setPool(d.items || []);
        setMeta(d.meta || null);
        if (!d.meta?.stale && d.count > 0) break;
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setBusy(false);
      setCycleStart(Date.now());
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Deals</h1>
          <p className="text-sm text-text-secondary mt-1">
            Real listings from eBay&apos;s own curated discount page. A new set
            every minute.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={togglePause}
            disabled={pool.length === 0}
          >
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button onClick={fetchNow} disabled={busy}>
            {busy ? "Fetching…" : "Refresh now"}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {/* Provenance strip. Every claim on this page is stated here once, in one
          place, rather than being implied by the layout. */}
      <Card className="!p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <Badge
            tone="verified"
            title="eBay selects these items. This app does not rank them."
          >
            curated by eBay
          </Badge>
          <span className="text-text-secondary">
            {meta ? `${meta.total} listing${meta.total === 1 ? "" : "s"}` : "—"}
            {meta && meta.unpriced > 0 && (
              <span className="text-text-dim">
                {" "}
                · {meta.unpriced} without a price read
              </span>
            )}
          </span>
          <span className="text-text-dim">
            updated {meta ? timeAgo(meta.last_fetched) : "—"}
          </span>
          {meta?.stale && (
            <Badge
              tone="warn"
              title={`Refreshed every ${Math.round((meta.refresh_interval_seconds || 3600) / 60)} minutes by a scheduled job.`}
            >
              stale
            </Badge>
          )}
          <span className="ml-auto flex items-center gap-3">
            <span className="text-text-dim tabular-nums">
              {paused
                ? "paused"
                : pool.length > 0 && pool.length > WINDOW
                  ? `next in ${remaining}s`
                  : ""}
            </span>
          </span>
        </div>
        {pool.length > WINDOW && (
          <div className="mt-2 h-0.5 bg-border/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-brand-lime/80 rounded-full"
              style={{ width: `${progress}%`, transition: "width 1s linear" }}
            />
          </div>
        )}
      </Card>

      {loading ? (
        <Card>
          <Spinner label="Loading deals…" />
        </Card>
      ) : pool.length === 0 ? (
        <Card>
          <EmptyState
            icon="🏷️"
            title="No deals stored yet"
            message="The board reads a stored pool so a page view never waits on eBay. Press Refresh now to collect it — the fetch takes about half a minute."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3 md:gap-4">
          {visible.map((item) => (
            <DealCard key={item.listing_id} item={item} />
          ))}
        </div>
      )}

      {pool.length > WINDOW && (
        <p className="text-xs text-text-dim">
          Showing {visible.length} of {pool.length}. Rotation only changes which
          of the stored listings you are looking at — nothing here is ranked by
          sales, because eBay does not publish that.
        </p>
      )}
    </div>
  );
}
