"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import Spinner from "@/components/Spinner";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  SELLER_DISCLAIMER,
  fetchSeller,
  formatAgeStats,
  formatConditionMix,
  formatFeedback,
  formatPriceStats,
  formatSellerRegion,
  sellerPagePath,
} from "@/lib/sellers";
import type { SellerFootprintResponse } from "@/lib/types";

/**
 * PHASE H - one seller's supply-side footprint.
 *
 * This is a read-only view over Browse readings that analyses already stored.
 * Feedback and account type are eBay's values, the region is the item
 * location eBay returned, and each distribution keeps its sample size. The
 * panel never computes a seller score and never shows a revenue, sales or
 * turnover figure: Browse does not expose a seller's transactions.
 *
 * The required disclaimer is at the foot. It is the boundary of the claim:
 * these were active listings when read, not a measure of what the seller has
 * actually sold.
 */

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string | number;
  note?: string | null;
}) {
  return (
    <div className="bg-bg-surface border border-border rounded-control px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-text-dim">
        {label}
      </div>
      <div className="text-sm font-semibold text-white break-words">
        {value}
      </div>
      {note && <div className="text-[11px] text-text-dim mt-1">{note}</div>}
    </div>
  );
}

function QueryContext({ result }: { result: SellerFootprintResponse }) {
  const context = result.query_context;
  if (!context) return null;
  return (
    <Card
      title="Query context"
      action={
        result.query ? <Badge tone="neutral">{result.query}</Badge> : undefined
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Stored observations" value={context.observations} />
        <Metric
          label="Latest sample"
          value={`${context.latest_listing_count} listing${
            context.latest_listing_count === 1 ? "" : "s"
          }`}
        />
        <Metric
          label="Latest observation"
          value={
            context.latest_observed_at
              ? formatDateTime(context.latest_observed_at)
              : "Not stored"
          }
        />
      </div>
      <p className="text-xs text-text-dim mt-3">
        The seller count above is how many of the latest sample&apos;s listings
        are this seller&apos;s. The latest sample is the whole query sample, not
        a census of the seller&apos;s current listings.
      </p>
      {result.query && (
        <Link
          href={sellerPagePath(result.username)}
          className="inline-block text-xs text-brand-lime hover:underline mt-2"
        >
          View all stored readings for this seller
        </Link>
      )}
    </Card>
  );
}

export default function SellerPanel({
  username,
  query,
}: {
  username: string;
  query: string;
}) {
  const [result, setResult] = useState<SellerFootprintResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setResult(null);
    fetchSeller(username, query || undefined, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setResult(payload);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof Error
            ? err.message
            : "Could not read the stored seller observations."
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [username, query]);

  const feedback = result
    ? formatFeedback(result.feedback?.percentage, result.feedback?.score)
    : null;
  const region = result
    ? formatSellerRegion(result.region?.country, result.region?.postal_code)
    : null;
  const conditions = result
    ? formatConditionMix(result.condition_mix.values)
    : null;
  const prices = result ? formatPriceStats(result.asking_prices) : null;
  const age = result ? formatAgeStats(result.listed_age) : null;
  const emptyMessage = result
    ? `${result.reason || "No stored Browse reading names this seller yet. This fills in as Analyze is used."}${
        result.query_context && result.query_context.observations > 0
          ? ` The latest stored sample has ${
              result.query_context.latest_listing_count
            } listing${
              result.query_context.latest_listing_count === 1 ? "" : "s"
            }.`
          : ""
      }`
    : "";

  return (
    <div className="max-w-6xl space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-bold text-white break-all">
            {result?.username || username}
          </h1>
          <Badge tone="neutral">Seller footprint</Badge>
        </div>
        <p className="text-sm text-text-secondary mt-1 max-w-3xl">
          A supply-side reading of the listings this app has seen from this
          seller. Feedback and account type are eBay&apos;s own values. The page
          reads stored Browse observations and spends no eBay call.
        </p>
      </div>

      {loading && (
        <Card>
          <Spinner label="Reading stored seller observations…" />
        </Card>
      )}

      {error && !loading && (
        <Card>
          <p className="text-sm text-accent-red">{error}</p>
          <p className="text-xs text-text-dim mt-2">
            The page could not reach the stored observations. It will not
            substitute an estimate.
          </p>
        </Card>
      )}

      {!loading && !error && result && result.observed_listings === 0 && (
        <Card>
          <EmptyState
            icon="🏷️"
            title="No observations for this seller"
            message={emptyMessage}
          />
        </Card>
      )}

      {!loading && !error && result && result.observed_listings > 0 && (
        <>
          <Card
            title="Seller"
            action={<Badge tone="neutral">Observed active listings</Badge>}
          >
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                label="Feedback"
                value={feedback || "Not stated"}
                note={
                  result.feedback
                    ? result.feedback.observed_at
                      ? `Read ${formatDateTime(result.feedback.observed_at)}`
                      : "Read time not stored"
                    : "eBay did not return a feedback value"
                }
              />
              <Metric
                label="Account type"
                value={result.account_type || "Not stated"}
                note="eBay's own value, kept verbatim"
              />
              <Metric
                label="Based"
                value={region || "Not stated"}
                note="Item location from eBay; not an inference"
              />
              <Metric
                label="Observed listings"
                value={result.observed_listings}
                note={
                  result.query
                    ? `in "${result.query}", active when read`
                    : "active when read, across stored readings"
                }
              />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-dim mt-3">
              <span>
                {result.readings} stored reading
                {result.readings === 1 ? "" : "s"}
              </span>
              {result.latest_observed_at && (
                <span>
                  Most recent reading:{" "}
                  {formatDateTime(result.latest_observed_at)}
                </span>
              )}
            </div>
          </Card>

          {result.query && <QueryContext result={result} />}

          <Card title="Condition mix">
            {conditions ? (
              <>
                <p className="text-lg font-semibold text-white">{conditions}</p>
                <p className="text-xs text-text-dim mt-1">
                  Share of {result.condition_mix.known} listing
                  {result.condition_mix.known === 1 ? "" : "s"} with a condition
                  read.
                  {result.condition_mix.unknown > 0 &&
                    ` Condition not read for ${result.condition_mix.unknown} listing${
                      result.condition_mix.unknown === 1 ? "" : "s"
                    }.`}
                </p>
              </>
            ) : (
              <p className="text-sm text-text-secondary">
                No condition was read for these listings, so no condition mix is
                claimed.
              </p>
            )}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Asking prices">
              {prices && result.asking_prices ? (
                <>
                  <p className="text-lg font-semibold text-white">{prices}</p>
                  <p className="text-xs text-text-dim mt-1">
                    {result.asking_prices.sample} of {result.observed_listings}{" "}
                    observed listing
                    {result.observed_listings === 1 ? "" : "s"} had a price and
                    currency read.
                  </p>
                </>
              ) : (
                <p className="text-sm text-text-secondary">
                  {result.asking_prices_reason ||
                    "No asking price was read for these listings."}
                </p>
              )}
            </Card>

            <Card title="Listed">
              {age && result.listed_age ? (
                <>
                  <p className="text-lg font-semibold text-white">
                    Listed {age} ago
                  </p>
                  <p className="text-xs text-text-dim mt-1">
                    {result.listed_age.sample} of {result.observed_listings}{" "}
                    observed listing
                    {result.observed_listings === 1 ? "" : "s"} had an eBay
                    creation date read.
                  </p>
                </>
              ) : (
                <p className="text-sm text-text-secondary">
                  {result.listed_age_reason ||
                    "No eBay creation date was read for these listings."}
                </p>
              )}
            </Card>
          </div>

          <p className="text-xs text-text-dim max-w-4xl">
            These are listings this app observed, not a census of the
            seller&apos;s inventory. A missing field is not zero, and a small
            sample is not the seller&apos;s whole business.
          </p>
        </>
      )}

      <p className="text-xs text-text-dim max-w-4xl border-t border-border pt-3">
        {SELLER_DISCLAIMER}
      </p>
    </div>
  );
}
