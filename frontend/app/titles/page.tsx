"use client";

import { FormEvent, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import Input, { Label } from "@/components/ui/Input";
import Spinner from "@/components/Spinner";
import {
  TITLE_MAX_CHARS,
  TITLE_SAMPLE_LIMIT,
  fetchTitleCounts,
  titleLength,
  titleLimitState,
  titleMeterLabel,
  titleMeterPercent,
  topTitleTerms,
} from "@/lib/titles";
import type { TitleCountsResponse } from "@/lib/types";

/**
 * PHASE F - the title helper.
 *
 * One query spends one Browse search. The page then shows the words and
 * adjacent pairs in the titles eBay actually returned, always beside the
 * number of listings that produced them. It does not estimate how often a
 * term is searched for: eBay gives this app no such figure, so no column for
 * one exists here.
 *
 * The meter below the tables is only a character counter for the title being
 * written. It counts with Array.from (one emoji is one character), caps its
 * bar at 100%, and lets the writer go past 80 so the over-limit state is
 * visible rather than silently truncating their work.
 */

const TOP_ROWS = 10;

function FrequencyTable({
  title,
  column,
  rows,
  total,
  empty,
}: {
  title: string;
  column: string;
  rows: { term: string; count: number }[];
  total: number;
  empty: string;
}) {
  return (
    <Card
      title={title}
      action={
        <span className="text-[11px] text-text-dim">
          {rows.length === 0 ? "none" : `${rows.length} of ${total}`}
        </span>
      }
    >
      {rows.length === 0 ? (
        <p className="py-6 text-sm leading-relaxed text-text-dim">{empty}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.08em] text-text-dim">
              <th scope="col" className="pb-2 text-left font-semibold">
                {column}
              </th>
              <th scope="col" className="pb-2 text-right font-semibold">
                Count
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.term} className="border-t border-border">
                <td className="py-2 pr-4 text-text-primary">{row.term}</td>
                <td className="py-2 text-right font-mono tabular-nums text-text-primary">
                  {row.count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function TitlesPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<TitleCountsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  async function run(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    // A new query must never sit under the previous query's counts while the
    // new sample is loading. Clear first, then replace with the new answer.
    setResult(null);
    try {
      const body = await fetchTitleCounts({
        q: trimmed,
        limit: TITLE_SAMPLE_LIMIT,
      });
      setResult(body);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The title counts could not be read"
      );
    } finally {
      setLoading(false);
    }
  }

  const draftLength = titleLength(draft);
  const overLimit = titleLimitState(draftLength) === "over";
  const overBy = draftLength - TITLE_MAX_CHARS;
  const words = result
    ? topTitleTerms(result.unigrams, TOP_ROWS).map((row) => ({
        term: row.word,
        count: row.count,
      }))
    : [];
  const phrases = result
    ? topTitleTerms(result.bigrams, TOP_ROWS).map((row) => ({
        term: row.phrase,
        count: row.count,
      }))
    : [];

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="text-xl font-bold text-text-primary">Title Helper</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Count the words and adjacent pairs in the titles eBay returns for a
          query. Every table names the sample behind it, so you can see the
          evidence before you write a title of your own.
        </p>
      </div>

      <Card title="Query">
        <form
          onSubmit={run}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <div className="min-w-0 flex-1">
            <Label htmlFor="title-query">Search eBay titles</Label>
            <Input
              id="title-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="garden hose"
              maxLength={200}
              autoComplete="off"
            />
          </div>
          <Button
            type="submit"
            disabled={loading || !query.trim()}
            className="shrink-0"
          >
            {loading ? "Reading titles…" : "Analyse titles"}
          </Button>
        </form>
        <p className="mt-2 text-[11px] leading-relaxed text-text-dim">
          One eBay Browse search per analysis, returning up to{" "}
          {TITLE_SAMPLE_LIMIT} New listings. The sample is the titles that
          search returned, without your buying price band.
        </p>
      </Card>

      {error && (
        <div
          role="alert"
          className="rounded-card border border-accent-red/40 bg-accent-red/10 px-4 py-3 text-sm text-accent-red"
        >
          {error}
        </div>
      )}

      {loading && (
        <Card>
          <div className="flex justify-center py-8">
            <Spinner label="Reading titles from eBay…" />
          </div>
        </Card>
      )}

      {!loading && !result && !error && (
        <Card>
          <EmptyState
            icon="🔤"
            title="No titles analysed yet"
            message="Enter a query above. One eBay Browse search returns the sample; these tables then count the titles it actually returned."
          />
        </Card>
      )}

      {!loading && result && (
        <section className="space-y-4" aria-live="polite">
          <div className="flex flex-wrap items-end justify-between gap-3 rounded-card border border-border bg-bg-secondary px-4 py-3 shadow-card">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim">
                Query
              </div>
              <div className="mt-0.5 truncate text-lg font-semibold text-white">
                {result.query}
              </div>
            </div>
            <div
              className="shrink-0 text-right"
              title="Every count below is computed from these listings."
            >
              <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim">
                Listings analysed
              </div>
              <div
                className={`font-mono text-2xl font-bold tabular-nums ${
                  result.listings_analysed > 0
                    ? "text-brand-lime"
                    : "text-text-primary"
                }`}
              >
                {result.listings_analysed}
              </div>
            </div>
          </div>

          {result.listings_analysed === 0 ? (
            <Card>
              <EmptyState
                icon="🧾"
                title="No listings to count"
                message={
                  result.reason ??
                  "eBay returned no active New listings for this query, so there are no title counts to report."
                }
              />
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <FrequencyTable
                title="Frequent words"
                column="Word"
                rows={words}
                total={result.unigrams.length}
                empty="None of these titles contained a countable word."
              />
              <FrequencyTable
                title="Phrase pairs"
                column="Pair"
                rows={phrases}
                total={result.bigrams.length}
                empty="None of these titles contained two countable words next to each other."
              />
            </div>
          )}
        </section>
      )}

      <Card
        title="Title being built"
        action={
          <span className="text-[11px] text-text-dim">
            eBay&apos;s limit is {TITLE_MAX_CHARS} characters
          </span>
        }
      >
        <Label htmlFor="title-draft">Draft title</Label>
        <Input
          id="title-draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Garden hose expandable 50ft anti-kink"
          autoComplete="off"
          aria-describedby="title-meter-help"
        />
        <div className="mt-3 flex items-center justify-between gap-3">
          <div
            role="progressbar"
            aria-label="Draft title length"
            aria-valuemin={0}
            aria-valuemax={TITLE_MAX_CHARS}
            aria-valuenow={Math.min(draftLength, TITLE_MAX_CHARS)}
            aria-valuetext={titleMeterLabel(draftLength)}
            className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-bg-surface"
          >
            <div
              className={`h-full rounded-full transition-[width] duration-150 ${
                overLimit ? "bg-accent-red" : "bg-brand-lime"
              }`}
              style={{ width: `${titleMeterPercent(draftLength)}%` }}
            />
          </div>
          <div
            className={`shrink-0 font-mono text-sm tabular-nums ${
              overLimit ? "text-accent-red" : "text-text-secondary"
            }`}
          >
            {titleMeterLabel(draftLength)}
          </div>
        </div>
        <p
          id="title-meter-help"
          className={`mt-1.5 text-[11px] ${
            overLimit ? "text-accent-red" : "text-text-dim"
          }`}
        >
          {overLimit
            ? `Over the limit by ${overBy} character${overBy === 1 ? "" : "s"}. Shorten before listing.`
            : draftLength === TITLE_MAX_CHARS
              ? "At the limit."
              : `${TITLE_MAX_CHARS - draftLength} characters left.`}
        </p>
      </Card>

      <p className="text-[11px] leading-relaxed text-text-dim">
        Each count is the number of listings whose title contains the word or
        adjacent pair, not the number of times it appears. Pairs are adjacent
        words where both are countable, so a stop word breaks the pair: “garden
        hose for sale” yields “garden hose”, never “hose sale”. Every figure is
        bounded by the Listings analysed sample above.
      </p>
    </div>
  );
}
