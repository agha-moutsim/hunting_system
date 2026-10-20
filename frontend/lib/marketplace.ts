"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "./api";
import {
  DEFAULT_MARKETPLACE_ID,
  getMarketplaceId,
  setMarketplaceId,
  subscribeMarketplace,
} from "./marketplaceId";
import type { MarketplaceInfo, MarketsResponse } from "./types";

/**
 * The UK record shown while `/api/markets` is in flight or unreachable.
 *
 * It mirrors config.MARKETPLACES rather than inventing data: the UK is the one
 * market with a fee table, and it is the historical default. A failure to list
 * markets must not make the app claim another currency.
 */
const UK_FALLBACK: MarketplaceInfo = {
  id: DEFAULT_MARKETPLACE_ID,
  label: "United Kingdom",
  country_code: "GB",
  currency: "GBP",
  currency_symbol: "£",
  fee_table: "uk-rate-card-2026-09-30",
  fee_warning: null,
  deals_url: "https://www.ebay.co.uk/deals",
  deals_http_status: 200,
  deals_checked_at: "2026-10-21",
};

let cached: MarketsResponse | null = null;
let inflight: Promise<MarketsResponse> | null = null;

/** Fetch the registry once per tab; a failure is reported, never hidden. */
export function fetchMarkets(): Promise<MarketsResponse> {
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = apiFetch<MarketsResponse>("/api/markets")
      .then((body) => {
        cached = body;
        return body;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Test helper: forget the module-level cache. */
export function resetMarketsCache(): void {
  cached = null;
  inflight = null;
}

export interface UseMarketplace {
  id: string;
  marketplace: MarketplaceInfo;
  marketplaces: MarketplaceInfo[];
  loading: boolean;
  error: string | null;
  selectMarketplace: (id: string) => void;
}

/**
 * The selected market and the list the selector may offer.
 *
 * `selectMarketplace` writes the id to localStorage and fires one event, so
 * every mounted surface (header, Deals, Fees, Analyze warnings) re-reads the
 * same value without a page reload.
 */
export function useMarketplace(): UseMarketplace {
  const [id, setId] = useState<string>(DEFAULT_MARKETPLACE_ID);
  const [marketplaces, setMarketplaces] = useState<MarketplaceInfo[]>(
    cached?.marketplaces ?? [UK_FALLBACK]
  );
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setId(getMarketplaceId());
    const unsubscribe = subscribeMarketplace(() => setId(getMarketplaceId()));
    let alive = true;
    setLoading(true);
    fetchMarkets()
      .then((body) => {
        if (!alive) return;
        setMarketplaces(
          body.marketplaces.length ? body.marketplaces : [UK_FALLBACK]
        );
        setError(null);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(
          err instanceof Error
            ? err.message
            : "Could not load the marketplace list."
        );
        setMarketplaces([UK_FALLBACK]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  const marketplace = useMemo(
    () => marketplaces.find((m) => m.id === id) ?? UK_FALLBACK,
    [id, marketplaces]
  );

  const selectMarketplace = useCallback((next: string) => {
    setMarketplaceId(next);
    setId(next);
  }, []);

  return {
    id,
    marketplace,
    marketplaces,
    loading,
    error,
    selectMarketplace,
  };
}
