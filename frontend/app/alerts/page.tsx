"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/EmptyState";
import Spinner from "@/components/Spinner";
import {
  ALERT_TABS,
  alertTypeLabel,
  alertUnit,
  fetchAlertCount,
  fetchAlerts,
  fetchNewMatches,
  fetchSavedSearches,
  formatAlertPair,
  markAlertRead,
  markAllAlertsRead,
  markMatchRead,
  runSavedSearch,
  unreadBadge,
  type AlertTabKey,
} from "@/lib/alerts";
import {
  formatDateTime,
  formatGBP,
  formatPercent,
  timeAgo,
} from "@/lib/format";
import type {
  PriceAlert,
  SavedSearch,
  SearchResult,
  SearchRunResponse,
} from "@/lib/types";

/**
 * PHASE E - the alerts inbox.
 *
 * This page compares nothing. Every row was written by hunter/alerts.py from
 * two real stored readings (a tracker price check, or the hourly alerts
 * pass), and the sentence on the row IS that comparison. The two stored
 * values are rendered in the row's own unit - money for price rows, percent
 * for margin rows - so a stored 33.5 can never read as GBP 33.50.
 *
 * The New matches tab reads saved-search results: written only when a run
 * found a named listing, a real supplier price and a margin that cleared the
 * search's own band and minimum. Running a search spends one Browse call, so
 * the card states that at the button and the run report states what it spent
 * - and, when it stored nothing, why.
 */

const LIST_LIMIT = 100;
const MATCH_LIMIT = 50;

const TONE_BY_TYPE: Record<string, string> = {
  price_drop: "pass",
  price_increase: "fail",
  target_hit: "info",
  margin_alert: "warn",
};

function AlertRow({
  alert,
  busy,
  onRead,
}: {
  alert: PriceAlert;
  busy: boolean;
  onRead: () => void;
}) {
  const unit = alertUnit(alert.alert_type);
  return (
    <div
      className={`flex items-start gap-3 border-b border-border px-4 py-3.5 transition-colors last:border-b-0 hover:bg-bg-surface/40 ${
        alert.is_read ? "" : "bg-brand-lime/[0.03]"
      }`}
    >
      <span
        aria-hidden
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
          alert.is_read ? "bg-border" : "bg-brand-lime"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-white">
            {alert.product_name || "Unnamed item"}
          </span>
          <Badge tone={TONE_BY_TYPE[alert.alert_type] || "neutral"}>
            {alertTypeLabel(alert.alert_type)}
          </Badge>
        </div>
        <p className="mt-1 text-sm leading-relaxed text-text-secondary">
          {alert.message}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div
          className="font-mono text-sm tabular-nums text-text-primary"
          title={
            unit === "margin"
              ? "The two margins this row compared"
              : "The two prices this row compared"
          }
        >
          {formatAlertPair(alert)}
        </div>
        <div
          className="mt-0.5 text-[11px] text-text-dim"
          title={formatDateTime(alert.created_at)}
        >
          {alert.created_at ? timeAgo(alert.created_at) : "unknown when"}
        </div>
        {!alert.is_read && (
          <button
            type="button"
            onClick={onRead}
            disabled={busy}
            className="mt-1 text-[11px] font-semibold text-accent-blue hover:text-white disabled:opacity-50"
          >
            {busy ? "Marking…" : "Mark read"}
          </button>
        )}
      </div>
    </div>
  );
}

function SearchRow({
  search,
  running,
  report,
  onRun,
}: {
  search: SavedSearch;
  running: boolean;
  report?: SearchRunResponse;
  onRun: () => void;
}) {
  const stored = report && !report.error && !report.reason;
  return (
    <div className="border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">
            {search.search_name}
          </div>
          <div className="mt-0.5 text-[12px] text-text-secondary">
            “{search.query}” · {formatGBP(search.price_min)}–
            {formatGBP(search.price_max)} · min margin{" "}
            {formatPercent(search.min_margin)}
            {!search.auto_run && (
              <span className="text-text-dim"> · manual only</span>
            )}
          </div>
          <div className="mt-1 text-[11px] text-text-dim">
            {search.last_run
              ? `last run ${timeAgo(search.last_run)}`
              : "never run"}{" "}
            · {search.result_count} stored match
            {search.result_count === 1 ? "" : "es"}
            {search.unread_count > 0 && (
              <span className="text-brand-lime">
                {" "}
                · {search.unread_count} unread
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          className="shrink-0 rounded-control border border-border bg-transparent px-3 py-1.5 text-xs font-semibold text-text-primary transition-colors hover:bg-bg-surface focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-lime disabled:cursor-not-allowed disabled:opacity-60"
        >
          {running ? "Running…" : "Run"}
        </button>
      </div>
      {report && (
        <p
          className={`mt-2 text-[11px] leading-relaxed ${
            stored ? "text-brand-lime" : "text-accent-amber"
          }`}
        >
          {report.error
            ? report.error
            : report.reason
              ? report.reason
              : `stored ${report.found} match${report.found === 1 ? "" : "es"}`}
          <span className="text-text-dim">
            {" "}
            · {report.browse_calls} Browse call
            {report.browse_calls === 1 ? "" : "s"}
          </span>
        </p>
      )}
    </div>
  );
}

function MatchRow({
  match,
  busy,
  onRead,
}: {
  match: SearchResult;
  busy: boolean;
  onRead: () => void;
}) {
  return (
    <div
      className={`flex items-start gap-3 border-b border-border px-4 py-3.5 last:border-b-0 ${
        match.is_read ? "" : "bg-brand-lime/[0.03]"
      }`}
    >
      <span
        aria-hidden
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
          match.is_read ? "bg-border" : "bg-brand-lime"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={match.ebay_url}
            target="_blank"
            rel="noreferrer"
            className="truncate text-sm font-semibold text-white hover:text-brand-lime"
          >
            {match.product_name || match.search_name}
          </a>
          <Badge tone={match.verdict || "pending"}>
            {match.verdict || "unrated"}
          </Badge>
          <span className="text-[11px] text-text-dim">
            from “{match.search_name}”
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-text-secondary">
          <span>
            eBay avg{" "}
            <span className="font-mono text-text-primary">
              {formatGBP(match.ebay_price)}
            </span>
          </span>
          <span>
            supplier{" "}
            <span className="font-mono text-text-primary">
              {formatGBP(match.supplier_price)}
            </span>
            {match.supplier_name ? ` (${match.supplier_name})` : ""}
          </span>
          <span>
            margin{" "}
            <span className="font-mono text-brand-lime">
              {formatPercent(match.margin)}
            </span>
          </span>
          <span>
            profit{" "}
            <span className="font-mono text-text-primary">
              {formatGBP(match.profit)}
            </span>
          </span>
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div
          className="text-[11px] text-text-dim"
          title={formatDateTime(match.found_at)}
        >
          {match.found_at ? timeAgo(match.found_at) : "unknown when"}
        </div>
        {!match.is_read && (
          <button
            type="button"
            onClick={onRead}
            disabled={busy}
            className="mt-1 text-[11px] font-semibold text-accent-blue hover:text-white disabled:opacity-50"
          >
            {busy ? "Marking…" : "Mark read"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function AlertsPage() {
  const [tab, setTab] = useState<AlertTabKey>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [matches, setMatches] = useState<SearchResult[]>([]);
  const [matchesUnread, setMatchesUnread] = useState(0);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [runReports, setRunReports] = useState<
    Record<number, SearchRunResponse>
  >({});

  const activeTab =
    ALERT_TABS.find((item) => item.key === tab) ?? ALERT_TABS[0];
  const alertType = activeTab.alertType;
  const readsMatches = Boolean(activeTab.readsMatches);

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const body = await fetchAlerts({
        unreadOnly,
        alertType,
        limit: LIST_LIMIT,
      });
      setAlerts(body.alerts || []);
      setTotal(body.total ?? 0);
      setUnread(body.unread ?? 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, [unreadOnly, alertType]);

  const loadMatches = useCallback(async () => {
    setMatchesLoading(true);
    try {
      const [saved, fresh] = await Promise.all([
        fetchSavedSearches(),
        fetchNewMatches(true, MATCH_LIMIT),
      ]);
      setSearches(saved.searches || []);
      setMatches(fresh.results || []);
      setMatchesUnread(fresh.unread_count ?? 0);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load saved searches"
      );
    } finally {
      setMatchesLoading(false);
    }
  }, []);

  // The inbox is the only tab that needs the alert list; the badge on its tab
  // still has to be right while another tab is open, so the count is fetched
  // once on mount as well.
  useEffect(() => {
    if (!readsMatches) return;
    fetchAlertCount()
      .then((body) => setUnread(body.unread ?? 0))
      .catch(() => {
        /* the visible error comes from the tab's own loader */
      });
  }, [readsMatches]);

  useEffect(() => {
    if (!readsMatches) void loadAlerts();
  }, [loadAlerts, readsMatches]);

  useEffect(() => {
    if (readsMatches) void loadMatches();
  }, [loadMatches, readsMatches]);

  async function readOne(id: number) {
    setBusyId(id);
    try {
      await markAlertRead(id);
      await loadAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark read");
    } finally {
      setBusyId(null);
    }
  }

  async function readAll() {
    setMarkingAll(true);
    try {
      await markAllAlertsRead();
      await loadAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark all read");
    } finally {
      setMarkingAll(false);
    }
  }

  async function readMatch(id: number) {
    setBusyId(id);
    try {
      await markMatchRead(id);
      await loadMatches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark read");
    } finally {
      setBusyId(null);
    }
  }

  async function runSearch(id: number) {
    setRunningId(id);
    setRunReports((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const report = await runSavedSearch(id);
      setRunReports((prev) => ({ ...prev, [id]: report }));
      await loadMatches();
    } catch (err) {
      setRunReports((prev) => ({
        ...prev,
        [id]: {
          found: 0,
          error: err instanceof Error ? err.message : "Run failed",
          reason: null,
          browse_calls: 0,
        },
      }));
    } finally {
      setRunningId(null);
    }
  }

  const badge = unreadBadge(unread);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Alerts
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary">
            Price moves, target hits and margin crossings, each compared from
            readings this app stored. A row only exists when two real values
            were compared — the sentence says which.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-pressed={unreadOnly}
            onClick={() => setUnreadOnly((value) => !value)}
            className={`rounded-control border px-3 py-1.5 text-xs font-semibold transition-colors ${
              unreadOnly
                ? "border-brand-lime/40 bg-brand-lime/15 text-brand-lime"
                : "border-border bg-transparent text-text-secondary hover:text-white"
            }`}
          >
            Unread only
          </button>
          <Button
            type="button"
            variant="secondary"
            onClick={readAll}
            disabled={unread === 0 || markingAll}
          >
            {markingAll ? "Marking…" : "Mark all read"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1 rounded-control border border-border p-1">
          {ALERT_TABS.map((item) => {
            const active = item.key === tab;
            return (
              <button
                key={item.key}
                type="button"
                aria-pressed={active}
                onClick={() => setTab(item.key)}
                className={`rounded-[6px] px-3 py-1.5 text-xs font-semibold transition-colors ${
                  active
                    ? "bg-accent-blue text-white"
                    : "text-text-secondary hover:bg-bg-surface hover:text-white"
                }`}
              >
                {item.label}
                {item.key === "all" && badge && (
                  <span className="ml-1.5 rounded-full bg-brand-lime px-1.5 text-[10px] font-bold text-brand-blue">
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="text-[11px] text-text-dim">
          {readsMatches
            ? `${matchesUnread} unread match${matchesUnread === 1 ? "" : "es"}`
            : `${unread} unread · ${total} in this view`}
        </div>
      </div>

      {error && (
        <div className="rounded-card border border-accent-red/40 bg-accent-red/10 px-4 py-3 text-sm text-accent-red">
          {error}
        </div>
      )}

      {readsMatches ? (
        <div className="space-y-4">
          <Card
            title="Saved searches"
            action={
              <span className="text-[11px] text-text-dim">
                one Browse call per run
              </span>
            }
          >
            {matchesLoading && searches.length === 0 ? (
              <div className="flex justify-center py-10">
                <Spinner label="Loading saved searches…" />
              </div>
            ) : searches.length === 0 ? (
              <EmptyState
                icon="🔎"
                title="No saved searches"
                message="Save a search on the Watchlist page. A run here re-checks it through the Hunter analysis and stores a match only when the result clears the search's own band and minimum margin."
                action={
                  <Link
                    href="/watchlist"
                    className="text-sm font-semibold text-accent-blue hover:text-white"
                  >
                    Open the Watchlist
                  </Link>
                }
              />
            ) : (
              searches.map((search) => (
                <SearchRow
                  key={search.id}
                  search={search}
                  running={runningId === search.id}
                  report={runReports[search.id]}
                  onRun={() => runSearch(search.id)}
                />
              ))
            )}
          </Card>

          <Card
            title="Unread matches"
            action={
              <span className="text-[11px] text-text-dim">
                {matchesUnread} waiting
              </span>
            }
          >
            {matchesLoading && matches.length === 0 ? (
              <div className="flex justify-center py-10">
                <Spinner label="Loading matches…" />
              </div>
            ) : matches.length === 0 ? (
              <EmptyState
                icon="🎯"
                title="No unread matches"
                message="Run a saved search to look again. A match is stored only when the analysis named a listing, found a real supplier price, and the result cleared the search's own filters."
              />
            ) : (
              matches.map((match) => (
                <MatchRow
                  key={match.id}
                  match={match}
                  busy={busyId === match.id}
                  onRead={() => readMatch(match.id)}
                />
              ))
            )}
          </Card>
        </div>
      ) : (
        <Card>
          {loading && alerts.length === 0 ? (
            <div className="flex justify-center py-10">
              <Spinner label="Loading alerts…" />
            </div>
          ) : alerts.length === 0 ? (
            <EmptyState
              icon="🔔"
              title={unreadOnly ? "No unread alerts" : "No alerts yet"}
              message="Alerts are written when two real readings differ — by a tracker price check, or by the hourly alerts pass. Nothing is compared on this page."
            />
          ) : (
            alerts.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                busy={busyId === alert.id}
                onRead={() => readOne(alert.id)}
              />
            ))
          )}
        </Card>
      )}

      <p className="text-[11px] leading-relaxed text-text-dim">
        Rows are written by the tracker check and the hourly alerts pass from
        stored readings; this page never compares prices itself. Margin rows
        name the two margins and the prices they came from, and say when postage
        paid was not given.
      </p>
    </div>
  );
}
