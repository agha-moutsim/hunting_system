"use client";

import { useEffect, useState, FormEvent } from "react";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input, { Label } from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import { apiFetch, apiPost, apiDelete } from "@/lib/api";
import {
  WatchlistItem,
  SavedSearch,
  SearchResult,
} from "@/lib/types";
import { formatGBP, formatPercent, formatDate } from "@/lib/format";

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<
    { kind: "watch" | "search"; id: number } | null
  >(null);

  // Add watch form
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [ebayPrice, setEbayPrice] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  // Search form
  const [sName, setSName] = useState("");
  const [sQuery, setSQuery] = useState("");
  const [sMin, setSMin] = useState("5");
  const [sMax, setSMax] = useState("35");
  const [sMargin, setSMargin] = useState("25");
  const [savingSearch, setSavingSearch] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [w, s, r] = await Promise.all([
        apiFetch<{ items: WatchlistItem[] }>("/api/watchlist"),
        apiFetch<{ searches: SavedSearch[] }>("/api/searches"),
        apiFetch<{ results: SearchResult[]; unread_count: number }>(
          "/api/searches/results?unread_only=false&limit=50"
        ),
      ]);
      setItems(w.items || []);
      setSearches(s.searches || []);
      setResults(r.results || []);
      setUnread(r.unread_count || 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function addWatch(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      await apiPost("/api/watchlist", {
        product_name: name.trim(),
        ebay_url: url.trim(),
        ebay_price: parseFloat(ebayPrice) || 0,
        target_price: parseFloat(targetPrice) || 0,
        supplier_price: 0,
        supplier_url: "",
        supplier_name: "",
        notes: notes.trim(),
      });
      setName("");
      setUrl("");
      setEbayPrice("");
      setTargetPrice("");
      setNotes("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Add failed");
    } finally {
      setSaving(false);
    }
  }

  async function addSearch(e: FormEvent) {
    e.preventDefault();
    if (!sName.trim() || !sQuery.trim() || savingSearch) return;
    setSavingSearch(true);
    try {
      await apiPost("/api/searches", {
        search_name: sName.trim(),
        query: sQuery.trim(),
        category: "",
        price_min: parseFloat(sMin) || 5,
        price_max: parseFloat(sMax) || 35,
        min_margin: parseFloat(sMargin) || 25,
        auto_run: true,
      });
      setSName("");
      setSQuery("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save search failed");
    } finally {
      setSavingSearch(false);
    }
  }

  async function runSearch(id: number) {
    setBusy(`run-${id}`);
    try {
      await apiPost(`/api/searches/${id}/run`, {});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setBusy(null);
    }
  }

  async function runAll() {
    setBusy("run-all");
    try {
      await apiPost("/api/searches/run-all", {});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run all failed");
    } finally {
      setBusy(null);
    }
  }

  async function markRead(id: number) {
    try {
      await apiPost(`/api/searches/results/${id}/read`, {});
      setResults((rs) =>
        rs.map((r) => (r.id === id ? { ...r, is_read: true } : r))
      );
      setUnread((u) => Math.max(0, u - 1));
    } catch {
      /* ignore */
    }
  }

  async function doConfirm() {
    if (!confirm) return;
    try {
      if (confirm.kind === "watch") {
        await apiDelete(`/api/watchlist/${confirm.id}`);
      } else {
        await apiDelete(`/api/searches/${confirm.id}`);
      }
      setConfirm(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const watchCols: Column<WatchlistItem>[] = [
    {
      key: "name",
      header: "Product",
      render: (r) => (
        <div>
          <div className="font-medium text-text-primary">{r.product_name}</div>
          {r.ebay_url && (
            <a
              href={r.ebay_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-accent-blue hover:underline"
            >
              eBay link
            </a>
          )}
          {r.notes && (
            <div className="text-xs text-text-dim mt-0.5">{r.notes}</div>
          )}
        </div>
      ),
      sortValue: (r) => r.product_name,
    },
    {
      key: "ebay",
      header: "eBay",
      align: "right",
      render: (r) => formatGBP(r.ebay_price),
      sortValue: (r) => r.ebay_price,
    },
    {
      key: "target",
      header: "Target",
      align: "right",
      render: (r) => formatGBP(r.target_price),
      sortValue: (r) => r.target_price,
    },
    {
      key: "added",
      header: "Added",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {formatDate(r.added_at)}
        </span>
      ),
      sortValue: (r) => r.added_at || "",
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <Button
          variant="danger"
          className="!px-2 !py-1 text-xs"
          onClick={() => setConfirm({ kind: "watch", id: r.id })}
        >
          Delete
        </Button>
      ),
    },
  ];

  const resultCols: Column<SearchResult>[] = [
    {
      key: "name",
      header: "Find",
      render: (r) => (
        <div>
          <div className="flex items-center gap-2">
            {!r.is_read && <Badge tone="warn">new</Badge>}
            <a
              href={r.ebay_url || "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-blue hover:underline font-medium line-clamp-2"
            >
              {r.product_name}
            </a>
          </div>
          <div className="text-xs text-text-dim">
            from “{r.search_name}” · {formatDate(r.found_at)}
          </div>
        </div>
      ),
      sortValue: (r) => r.product_name,
    },
    {
      key: "ebay",
      header: "eBay",
      align: "right",
      render: (r) => formatGBP(r.ebay_price),
      sortValue: (r) => r.ebay_price,
    },
    {
      key: "supplier",
      header: "Supplier",
      align: "right",
      render: (r) => formatGBP(r.supplier_price),
      sortValue: (r) => r.supplier_price,
    },
    {
      key: "margin",
      header: "Margin",
      align: "right",
      render: (r) => (
        <span
          className={r.margin >= 25 ? "text-accent-green" : "text-accent-amber"}
        >
          {formatPercent(r.margin)}
        </span>
      ),
      sortValue: (r) => r.margin,
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (r) => (
        <Badge tone={(r.verdict || "pending").toLowerCase()}>
          {(r.verdict || "pending").toUpperCase()}
        </Badge>
      ),
      sortValue: (r) => r.verdict || "",
    },
    {
      key: "read",
      header: "",
      align: "right",
      render: (r) =>
        !r.is_read ? (
          <Button
            variant="ghost"
            className="!px-2 !py-1 text-xs"
            onClick={() => markRead(r.id)}
          >
            Mark read
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Watchlist</h1>
          <p className="text-sm text-text-secondary mt-1">
            Saved products, saved searches, and new finds
            {unread > 0 && (
              <>
                {" "}
                · <Badge tone="warn">{unread} new</Badge>
              </>
            )}
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={runAll}
          disabled={busy != null || searches.length === 0}
        >
          {busy === "run-all" ? "Running…" : "Run all searches"}
        </Button>
      </div>

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Add to watchlist">
          <form onSubmit={addWatch} className="space-y-3">
            <div>
              <Label>Product name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Product name"
                required
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label>eBay price</Label>
                <Input
                  type="number"
                  step="0.01"
                  value={ebayPrice}
                  onChange={(e) => setEbayPrice(e.target.value)}
                  placeholder="19.99"
                />
              </div>
              <div>
                <Label>Target</Label>
                <Input
                  type="number"
                  step="0.01"
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(e.target.value)}
                  placeholder="14.99"
                />
              </div>
              <div>
                <Label>eBay URL</Label>
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://…"
                />
              </div>
            </div>
            <div>
              <Label>Notes</Label>
              <Input
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Optional notes…"
              />
            </div>
            <Button type="submit" disabled={saving} className="w-full">
              {saving ? "Adding…" : "Add to watchlist"}
            </Button>
          </form>
        </Card>

        <Card title="Save a search">
          <form onSubmit={addSearch} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Search name</Label>
                <Input
                  value={sName}
                  onChange={(e) => setSName(e.target.value)}
                  placeholder="My gadgets search"
                  required
                />
              </div>
              <div>
                <Label>Query</Label>
                <Input
                  value={sQuery}
                  onChange={(e) => setSQuery(e.target.value)}
                  placeholder="wireless earbuds"
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label>Price min</Label>
                <Input
                  type="number"
                  step="0.5"
                  value={sMin}
                  onChange={(e) => setSMin(e.target.value)}
                />
              </div>
              <div>
                <Label>Price max</Label>
                <Input
                  type="number"
                  step="0.5"
                  value={sMax}
                  onChange={(e) => setSMax(e.target.value)}
                />
              </div>
              <div>
                <Label>Min margin %</Label>
                <Input
                  type="number"
                  step="1"
                  value={sMargin}
                  onChange={(e) => setSMargin(e.target.value)}
                />
              </div>
            </div>
            <Button type="submit" disabled={savingSearch} className="w-full">
              {savingSearch ? "Saving…" : "Save search"}
            </Button>
          </form>
        </Card>
      </div>

      {/* Saved searches */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">
          Saved Searches ({searches.length})
        </h3>
        {loading ? (
          <Card>
            <Spinner label="Loading searches…" />
          </Card>
        ) : searches.length === 0 ? (
          <Card>
            <EmptyState
              icon="🔍"
              title="No saved searches"
              message="Save a search above to auto-find matching products with good margins."
            />
          </Card>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {searches.map((s) => (
              <div
                key={s.id}
                className="bg-bg-secondary border border-border rounded-xl p-4"
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="font-medium text-text-primary text-sm">
                    {s.search_name}
                  </div>
                  <Button
                    variant="danger"
                    className="!px-2 !py-1 text-xs"
                    onClick={() => setConfirm({ kind: "search", id: s.id })}
                  >
                    ✕
                  </Button>
                </div>
                <div className="text-xs text-text-secondary space-y-1 mb-3">
                  <div>Query: “{s.query}”</div>
                  <div>
                    £{s.price_min}–£{s.price_max} · margin ≥ {s.min_margin}%
                  </div>
                  <div className="text-text-dim">
                    {s.result_count} results · {s.unread_count} unread
                  </div>
                </div>
                <Button
                  variant="secondary"
                  className="w-full !py-1.5 text-xs"
                  onClick={() => runSearch(s.id)}
                  disabled={busy != null}
                >
                  {busy === `run-${s.id}` ? "Running…" : "Run now"}
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* New finds */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">
          New Finds ({results.length})
        </h3>
        <DataTable
          columns={resultCols}
          rows={results}
          keyFn={(r) => r.id}
          emptyMessage="No search results yet — run a saved search above."
        />
      </div>

      {/* Watchlist items */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">
          Watched Products ({items.length})
        </h3>
        <DataTable
          columns={watchCols}
          rows={items}
          keyFn={(r) => r.id}
          emptyMessage="Your watchlist is empty — add a product above."
        />
      </div>

      <ConfirmDialog
        open={confirm != null}
        title={
          confirm?.kind === "search" ? "Delete saved search?" : "Remove watchlist item?"
        }
        message="This cannot be undone."
        onConfirm={doConfirm}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
