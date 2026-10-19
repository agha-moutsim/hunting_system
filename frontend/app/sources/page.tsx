"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/Spinner";
import EmptyState from "@/components/EmptyState";
import SourcesTable from "@/components/SourcesTable";
import { apiFetch } from "@/lib/api";
import type { ProductDetail } from "@/lib/types";
import { demandSourceRows } from "@/lib/sourcesRows";

/**
 * PHASE C — Sources: where every figure about one product came from, and which
 * figures were never measured at all.
 *
 * Reached from History with `?product=<id>`, which is the only place a stored
 * product exists to ask about. Nothing on this page is computed from a rule of
 * thumb: the rows come from the stored analysis, and the "not known" list is
 * the rows whose values are null — so "no sales figure" can never be shown as
 * "0 sales", and a field this app has no way to fill says what would fill it.
 */
function SourcesView() {
  const params = useSearchParams();
  const productId = params.get("product");

  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await apiFetch<ProductDetail>(`/api/history/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (productId) void load(productId);
  }, [productId, load]);

  if (!productId) {
    return (
      <div className="mx-auto max-w-4xl space-y-6">
        <Header />
        <EmptyState
          title="No product selected"
          message="Open a product in History and choose Sources to see where each of its figures came from."
        />
        <p className="text-center">
          <Link
            href="/history"
            className="text-sm font-semibold text-brand-lime hover:underline"
          >
            Go to History
          </Link>
        </p>
      </div>
    );
  }

  const rows = demandSourceRows(detail?.demand);
  const salesRows = rows.filter((r) => !r.supply);
  const supplyRows = rows.filter((r) => r.supply);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Header title={detail?.product.title} />

      {loading && (
        <Card>
          <Spinner label="Loading sources…" />
        </Card>
      )}

      {error && (
        <Card className="border-accent-red/40">
          <div className="text-sm text-accent-red">⚠️ {error}</div>
        </Card>
      )}

      {!loading && detail && (
        <>
          <Card
            title="Sales evidence"
            action={
              detail.demand?.verified ? (
                <Badge
                  tone="verified"
                  title="The stored row carries a verified stamp"
                >
                  Verified
                </Badge>
              ) : (
                <Badge
                  tone="unverified"
                  title="The stored row does not carry a verified stamp"
                >
                  Unverified
                </Badge>
              )
            }
          >
            <SourcesTable rows={salesRows} />
          </Card>

          <Card
            title="Live listings"
            action={
              <span className="text-[11px] uppercase tracking-[0.08em] text-text-dim">
                supply, not sales
              </span>
            }
          >
            <SourcesTable rows={supplyRows} />
          </Card>

          <Card title="What the stored row says about itself">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
              data_source
            </p>
            <p className="mt-2 rounded-card border border-border/40 bg-bg-surface/40 px-4 py-3 font-mono text-[12px] leading-relaxed text-text-secondary">
              {detail.demand?.data_source ||
                "recorded before this field existed"}
            </p>
            <p className="mt-2 text-[12px] leading-relaxed text-text-dim">
              This is the sentence the analysis wrote when it stored the row: it
              names the query that produced the figures, and the source of any
              sold figure that did not come from that query.
            </p>
          </Card>
        </>
      )}

      {!loading && !detail && !error && (
        <EmptyState
          title="No stored analysis"
          message="This product has no saved analysis yet, so there is nothing to attribute."
        />
      )}
    </div>
  );
}

function Header({ title }: { title?: string }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-bold text-text-primary">Sources</h1>
        <p className="mt-1 text-sm text-text-secondary">
          {title
            ? title
            : "Where every figure about a product came from — and what is not known."}
        </p>
      </div>
      <Link
        href="/history"
        className="text-sm font-semibold text-text-secondary hover:text-white"
      >
        ← History
      </Link>
    </div>
  );
}

/**
 * `useSearchParams` suspends, and this page is prerendered as static content:
 * without a boundary the production build fails rather than rendering late.
 */
export default function SourcesPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-4xl">
          <Card>
            <Spinner label="Loading sources…" />
          </Card>
        </div>
      }
    >
      <SourcesView />
    </Suspense>
  );
}
