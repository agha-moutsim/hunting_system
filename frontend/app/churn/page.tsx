"use client";

import { FormEvent, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import Input, { Label } from "@/components/ui/Input";
import ListingAge from "@/components/ListingAge";
import Spinner from "@/components/Spinner";
import { churnIsClaimable, fetchChurn, formatListingPrice } from "@/lib/churn";
import { formatDate } from "@/lib/format";
import type { ChurnListing, ChurnResponse } from "@/lib/types";

/**
 * PHASE G - listing age and churn.
 *
 * This page is read-only. The observations were stored by analyses that
 * already spent their Browse call, so opening or querying this page spends
 * none. A listing that was in an earlier stored search result set and is
 * absent from the latest one is shown as "no longer listed", with the date it
 * was last seen. The page never says why it disappeared; eBay does not tell
 * this app that. It also never turns the small sample into a market rate.
 */

function ListingName({ row }: { row: ChurnListing }) {
  const label = row.title?.trim() || `Listing ${row.listing_id}`;
  if (!row.item_url) return <span>{label}</span>;
  return (
    <a
      href={row.item_url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-text-primary hover:text-brand-lime underline-offset-2 hover:underline"
    >
      {label}
    </a>
  );
}

function ListingTable({
  rows,
  mode,
}: {
  rows: ChurnListing[];
  mode: "churned" | "latest";
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-text-dim border-b border-border">
            <th className="py-2 pr-4 font-medium">Listing</th>
            <th className="py-2 pr-4 font-medium">Price</th>
            <th className="py-2 pr-4 font-medium">First seen</th>
            <th className="py-2 font-medium">
              {mode === "churned" ? "Status" : "Age"}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.listing_id}
              className="border-b border-border/60 last:border-0 align-top"
            >
              <td className="py-3 pr-4 max-w-[26rem]">
                <ListingName row={row} />
                <div className="text-[10px] text-text-dim mt-0.5">
                  {row.listing_id}
                </div>
              </td>
              <td className="py-3 pr-4 whitespace-nowrap text-text-secondary">
                {formatListingPrice(row.price, row.currency)}
              </td>
              <td className="py-3 pr-4 whitespace-nowrap text-text-secondary">
                {formatDate(row.first_seen_at)}
              </td>
              <td className="py-3">
                {mode === "churned" ? (
                  <ListingAge
                    status="no_longer_listed"
                    lastSeenAt={row.last_seen_at}
                  />
                ) : (
                  <ListingAge
                    age={row.age}
                    firstSeenAt={row.first_seen_at}
                    reason={row.age_reason}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-bg-surface border border-border rounded-control px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-text-dim">
        {label}
      </div>
      <div className="text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

function churnSuppressionTitle(result: ChurnResponse): string {
  if (result.observations < 2) return "Not enough observations yet";
  return "Samples are not comparable";
}

function churnSuppressionMessage(result: ChurnResponse): string {
  const reason = result.reason || "Churn needs a second observation.";
  if (result.observations < 2) {
    // The empty state named in design.md: a normal state, not an error and not
    // a zero. It says how it fills in rather than leaving a blank.
    return `${reason} This fills in as the tool is used.`;
  }
  return reason;
}

export default function ChurnPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ChurnResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function read(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    try {
      setResult(await fetchChurn(trimmed));
    } catch (err) {
      setResult(null);
      setError(
        err instanceof Error
          ? err.message
          : "Could not read the stored observations."
      );
    } finally {
      setLoading(false);
    }
  }

  const sampleCeiling =
    result?.limit != null
      ? `Up to ${result.limit} listings per observation`
      : "Sample ceiling not recorded";

  return (
    <div className="max-w-6xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Listing age and churn</h1>
        <p className="text-sm text-text-secondary mt-1 max-w-3xl">
          Age is read from eBay&apos;s own creation date. Churn compares the
          search result sets already stored by Analyze: a listing in an earlier
          observation and missing from the latest one is shown as{" "}
          <span className="text-white font-medium">no longer listed</span>, with
          the date it was last seen. Nothing here claims why a listing
          disappeared.
        </p>
      </div>

      <Card title="Read a query's observations">
        <form
          onSubmit={read}
          className="flex flex-col sm:flex-row sm:items-end gap-3"
        >
          <div className="flex-1">
            <Label htmlFor="churn-query">Query</Label>
            <Input
              id="churn-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="garden hose"
              autoComplete="off"
              maxLength={200}
            />
          </div>
          <Button type="submit" disabled={loading || !query.trim()}>
            {loading ? "Reading…" : "Read observations"}
          </Button>
        </form>
        <p className="text-xs text-text-dim mt-3">
          This page spends no eBay Browse call. Run Analyze on a query to add a
          new observation; the same price filter and sample size are required
          before two observations can be compared.
        </p>
      </Card>

      {error && (
        <Card>
          <p className="text-sm text-accent-red">{error}</p>
        </Card>
      )}

      {loading && (
        <Card>
          <Spinner label="Reading stored observations…" />
        </Card>
      )}

      {!loading && !result && !error && (
        <Card>
          <EmptyState
            icon="🕒"
            title="No query read yet"
            message="Enter a query that has been analyzed before. The page reads stored observations and never searches eBay itself."
          />
        </Card>
      )}

      {result && !loading && (
        <>
          <Card title="Observation sample">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Summary label="Query" value={result.query} />
              <Summary label="Observations" value={result.observations} />
              <Summary
                label="Latest observation"
                value={formatDate(result.latest_observed_at)}
              />
              <Summary
                label="Latest sample"
                value={`${result.latest_listing_count} listing${
                  result.latest_listing_count === 1 ? "" : "s"
                }`}
              />
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-dim mt-3">
              <span>{sampleCeiling}</span>
              <span>
                Listings seen in earlier observations:{" "}
                {result.earlier_listing_count}
              </span>
              {result.previous_observed_at && (
                <span>
                  Previous observation:{" "}
                  {formatDate(result.previous_observed_at)}
                </span>
              )}
            </div>
          </Card>

          {!churnIsClaimable(result) ? (
            <Card title="Churn not claimed">
              <EmptyState
                icon="🕒"
                title={churnSuppressionTitle(result)}
                message={churnSuppressionMessage(result)}
              />
            </Card>
          ) : (
            <Card
              title="Listings observed before, not present in the latest observation."
              action={
                <span className="text-xs text-text-dim">
                  {result.churned?.length ?? 0} of{" "}
                  {result.earlier_listing_count} earlier listings
                </span>
              }
            >
              {result.churned && result.churned.length > 0 ? (
                <ListingTable rows={result.churned} mode="churned" />
              ) : (
                <EmptyState
                  icon="✅"
                  title="No missing listings"
                  message={
                    result.reason ||
                    "No listing observed earlier is missing from the latest observation."
                  }
                />
              )}
            </Card>
          )}

          <Card
            title="Present in the latest observation"
            action={
              <span className="text-xs text-text-dim">
                {result.latest_listing_count} listing
                {result.latest_listing_count === 1 ? "" : "s"}
              </span>
            }
          >
            {result.latest.length > 0 ? (
              <ListingTable rows={result.latest} mode="latest" />
            ) : (
              <EmptyState
                icon="🔎"
                title="The latest observation returned no listings"
                message="That is a measured empty result, not a missing search. It does not say why eBay returned nothing."
              />
            )}
          </Card>

          <p className="text-xs text-text-dim max-w-4xl">
            A listing missing from the latest sample may simply not have been
            returned in this small search sample. The page reports what the
            stored observations contain; it does not turn them into a market
            rate or a reason.
          </p>
        </>
      )}
    </div>
  );
}
