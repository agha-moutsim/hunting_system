"use client";

import Link from "next/link";
import {
  ScrapedProduct,
  DemandData,
  LLMAnalysis,
  ProvenanceBlock,
  ProvenanceInfo,
  VerdictData,
} from "@/lib/types";
import Badge from "@/components/ui/Badge";
import OutsideBandBadge from "@/components/ui/OutsideBandBadge";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";
import FilterChecks from "@/components/FilterChecks";
import { fieldProvenance, infoTitle } from "@/lib/provenance";
import { saleEvidence } from "@/lib/saleEvidence";
import { sellerPagePath } from "@/lib/sellers";
import { formatGBP, formatObservedAt, formatPercent } from "@/lib/format";
import { SoldPriceDistribution } from "@/components/charts";
import SupplierCard from "@/components/SupplierCard";

/**
 * Product results dashboard.
 *
 * Presentation only — every value, label and API contract is unchanged. The
 * goal is hierarchy: a reader should reach "should I buy this?" in one
 * glance, then the evidence behind it, then the raw AI text if they want it.
 *
 * Two rules carry through from C13: an unmeasured value says so rather than
 * showing a dash that reads as zero, and the provenance badge always travels
 * with the number it qualifies.
 */

function Metric({
  label,
  value,
  prov,
  emphasis = false,
}: {
  label: string;
  value: React.ReactNode;
  prov?: ProvenanceInfo;
  emphasis?: boolean;
}) {
  return (
    <div
      className={`rounded-card border px-4 py-3 transition-colors duration-200 ${
        emphasis
          ? "bg-bg-surface border-border/70 shadow-card"
          : "bg-bg-surface/40 border-border/40 hover:border-border/70 hover:bg-bg-surface/70"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
          {label}
        </span>
        {prov && (
          <ProvenanceBadge
            provenance={prov.provenance}
            label={prov.label}
            title={infoTitle(prov)}
          />
        )}
      </div>
      <div className="mt-2 font-mono text-lg font-semibold tabular-nums tracking-tight text-white">
        {value}
      </div>
    </div>
  );
}

/**
 * PHASE C — stated wherever a search-page count is what the reader is looking
 * at, and nowhere else.
 *
 * The count above it is real: it is how many live listings an eBay search
 * returned. The sentence exists because a count of listings is the one number
 * on this screen a reader is most likely to read as a count of sales, and this
 * app cannot turn one into the other — it has no sold-listing search at all.
 */
function NoSalesTotalNote({ className = "" }: { className?: string }) {
  return (
    <p
      className={`rounded-card border border-border/40 bg-bg-surface/30 px-4 py-3 text-[12px] leading-relaxed text-text-dim ${className}`}
    >
      <span className="font-medium text-text-secondary">
        That is a search-page count.
      </span>{" "}
      It is how many live listings eBay returned, not how many sold. No sales
      figure is held for this product, and one cannot be derived from listings:
      an asking price is not evidence of a sale. A sale can only be verified
      from your own eBay purchase history.
    </p>
  );
}

function SectionTitle({
  children,
  hint,
}: {
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <h3 className="flex items-center gap-2.5 text-sm font-semibold tracking-tight text-white">
        <span
          aria-hidden
          className="h-3.5 w-[3px] shrink-0 rounded-full bg-brand-lime"
        />
        {children}
      </h3>
      {hint && (
        <span className="truncate text-[11px] uppercase tracking-[0.08em] text-text-dim">
          {hint}
        </span>
      )}
      <span aria-hidden className="h-px flex-1 bg-border/40" />
    </div>
  );
}

function LlmLine({
  label,
  value,
  reasoning,
  toneMap,
}: {
  label: string;
  value?: string | null;
  reasoning?: string | null;
  toneMap?: Record<string, string>;
}) {
  if (!value) return null;
  const key = value.toLowerCase();
  const tone =
    toneMap?.[key] ||
    (["generic", "strong", "source", "pass"].includes(key)
      ? "pass"
      : ["branded", "weak", "skip", "fail"].includes(key)
        ? "fail"
        : ["ambiguous", "moderate", "investigate", "pending"].includes(key)
          ? "pending"
          : "info");
  return (
    <div className="flex flex-col gap-1.5 rounded-card border border-border/40 bg-bg-surface/40 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
          {label}
        </span>
        <Badge tone={tone}>{value}</Badge>
      </div>
      {reasoning && (
        <p className="text-[13px] leading-relaxed text-text-secondary">
          {reasoning}
        </p>
      )}
    </div>
  );
}

export default function Scorecard({
  ebayProduct,
  demand,
  suppliers,
  llmAnalysis,
  verdict,
  scorecard,
  provenance,
  sellerQuery,
}: {
  ebayProduct: ScrapedProduct;
  demand?: DemandData | null;
  suppliers: ScrapedProduct[];
  llmAnalysis?: LLMAnalysis | null;
  verdict?: VerdictData | null;
  scorecard?: string;
  provenance?: ProvenanceBlock;
  /** The search lane this result came from, when it was not a URL analysis. */
  sellerQuery?: string | null;
}) {
  const v = (verdict?.verdict || "pending").toLowerCase();
  // Two price ranges, kept apart. One is a SALE range and only exists when a
  // sale was observed; the other is what live listings are ASKING right now.
  // They are never merged, and each tile is labelled to match the range beside
  // it — a figure built from asking prices is not captioned "sold".
  const soldRange =
    demand &&
    demand.lowest_sold_price != null &&
    demand.highest_sold_price != null
      ? `${formatGBP(demand.lowest_sold_price)} – ${formatGBP(demand.highest_sold_price)}`
      : "⚠️ Unverified";
  const activeRange =
    demand &&
    demand.lowest_active_price != null &&
    demand.highest_active_price != null
      ? `${formatGBP(demand.lowest_active_price)} – ${formatGBP(demand.highest_active_price)}`
      : "⚠️ Unverified";
  // Which KIND of evidence this run actually holds. Each block below renders
  // only on its own evidence, so the screen can never put an empty "Sold" row
  // beside a populated "Live listings" one and invite them to be read as the
  // same measurement.
  //
  // PHASE C — the rules that decide which figure is primary, whether it may be
  // called verified, and whether the reader is owed the search-page note live
  // in `lib/saleEvidence.ts`, where they can be tested. The sales block used to
  // be gated on `sold_count_30d`, a figure no source this app can reach
  // produces, so a captured 7-day sale was stored and then never shown.
  const sale = saleEvidence(demand);
  const { figure: saleFigure, stamp: saleStamp, verified: saleVerified } = sale;
  const soldCount30d = demand?.sold_count_30d ?? null;
  const hasSaleEvidence = sale.hasSaleEvidence;
  const hasActive = sale.hasSearchCount;

  // Section-level stamp: the provenance block wins, else the demand object's
  // own tier. Undefined = no badge at all (never a fabricated one).
  const demandProv: ProvenanceInfo | undefined =
    provenance?.demand ??
    (demand?.provenance
      ? { provenance: demand.provenance, label: demand.provenance_label }
      : undefined);
  const demandField = (name: string, ...aliases: string[]) =>
    fieldProvenance(provenance?.fields, name, ...aliases);

  const profit = verdict?.profit ?? null;
  const margin = verdict?.margin ?? null;

  return (
    <div className="space-y-8">
      {/* ---------------------------------------------------------------- */}
      {/* Hero — what the product is and what it costs                  */}
      {/* ---------------------------------------------------------------- */}
      <section className="overflow-hidden rounded-panel border border-border/60 bg-bg-secondary shadow-panel">
        <div className="flex flex-col gap-6 p-5 sm:flex-row md:p-6">
          {ebayProduct.image_url && (
            <div className="w-full shrink-0 sm:w-44">
              <div className="overflow-hidden rounded-card border border-border/50 bg-bg-primary/60">
                <img
                  src={ebayProduct.image_url}
                  alt={ebayProduct.title || "Product image"}
                  className="aspect-square w-full object-contain p-3"
                />
              </div>
            </div>
          )}

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h2 className="max-w-2xl text-balance text-xl font-semibold leading-snug tracking-tight text-white sm:text-2xl">
                {ebayProduct.title}
              </h2>
              <Badge tone={v}>{v.toUpperCase()}</Badge>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <Metric
                label="Listed price"
                emphasis
                value={
                  <span className="inline-flex flex-wrap items-center gap-2">
                    {formatGBP(ebayProduct.price)}
                    {ebayProduct.outside_band && <OutsideBandBadge />}
                  </span>
                }
              />
              <Metric
                label="Condition"
                value={ebayProduct.condition || "Not stated"}
              />
              <Metric
                label="Seller"
                value={
                  ebayProduct.seller ? (
                    <Link
                      href={sellerPagePath(ebayProduct.seller, sellerQuery)}
                      className="text-brand-lime underline-offset-2 hover:underline"
                      title="View this seller's stored footprint"
                    >
                      {ebayProduct.seller}
                    </Link>
                  ) : (
                    "Not stated"
                  )
                }
              />
            </div>

            {ebayProduct.url && (
              <a
                href={ebayProduct.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group mt-5 inline-flex items-center gap-1.5 rounded-control text-sm font-medium text-brand-lime underline-offset-4 transition-colors duration-200 hover:text-white hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand-lime"
              >
                View this listing on eBay
                <span
                  aria-hidden
                  className="transition-transform duration-200 group-hover:translate-x-0.5"
                >
                  →
                </span>
              </a>
            )}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* Decision — the numbers a buyer acts on                        */}
      {/* ---------------------------------------------------------------- */}
      {verdict && (
        <section>
          <SectionTitle hint="net of fees and shipping">Decision</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Net profit"
              emphasis
              prov={provenance?.profit_analysis}
              value={
                profit == null ? (
                  <span className="text-text-dim">—</span>
                ) : (
                  <span
                    className={
                      profit > 0 ? "text-brand-lime" : "text-accent-red"
                    }
                  >
                    {formatGBP(profit)}
                  </span>
                )
              }
            />
            <Metric
              label="Margin"
              emphasis
              prov={provenance?.profit_analysis}
              value={
                margin == null ? (
                  <span className="text-text-dim">—</span>
                ) : (
                  formatPercent(margin)
                )
              }
            />
            <Metric
              label="Assessment"
              emphasis
              value={<Badge tone={v}>{v.toUpperCase()}</Badge>}
            />
          </div>
          <div className="mt-4 space-y-2">
            <FilterChecks filters={verdict.filters || []} />
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Price comparison                                                */}
      {/* ---------------------------------------------------------------- */}
      {suppliers.length > 0 && (
        <section>
          <SectionTitle hint="what you pay vs what you sell">
            Price comparison
          </SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <Metric
              label="eBay price"
              emphasis
              value={formatGBP(ebayProduct.price)}
            />
            {suppliers.map((s, i) => {
              const delta = ebayProduct.price - s.price;
              return (
                <Metric
                  key={i}
                  label={s.source}
                  value={
                    <span className="flex flex-col gap-1">
                      <span>{formatGBP(s.price)}</span>
                      <span
                        className={`text-xs font-medium ${
                          delta > 0 ? "text-brand-lime" : "text-accent-red"
                        }`}
                      >
                        {delta > 0 ? "+" : ""}
                        {formatGBP(delta)}
                      </span>
                    </span>
                  }
                />
              );
            })}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Supplier detail                                                */}
      {/* ---------------------------------------------------------------- */}
      {suppliers.length > 0 && (
        <section>
          <SectionTitle hint={`${suppliers.length} matched`}>
            Suppliers
          </SectionTitle>
          <div className="space-y-3">
            {suppliers.map((s, i) => (
              <SupplierCard
                key={i}
                supplier={s}
                ebayPrice={ebayProduct.price}
              />
            ))}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Demand                                                          */}
      {/* ---------------------------------------------------------------- */}
      <section>
        <SectionTitle hint="eBay evidence">Demand</SectionTitle>
        {hasSaleEvidence || hasActive ? (
          <>
            {hasSaleEvidence && (
              <div className="rounded-card border border-brand-lime/25 bg-brand-lime/[0.03] p-4">
                <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-brand-lime/90">
                    {sale.title}
                  </span>
                  <span className="h-px flex-1 bg-border/40" />
                  <span className="text-[11px] text-text-dim">
                    {sale.readAt
                      ? `read ${formatObservedAt(sale.readAt)}`
                      : "read time not recorded"}
                  </span>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Metric
                    label="Sold (7d)"
                    emphasis
                    prov={saleStamp ?? undefined}
                    value={
                      saleFigure?.value ?? (
                        <span className="text-accent-amber">Not stated</span>
                      )
                    }
                  />
                  {soldCount30d != null && (
                    <Metric
                      label="Sold (30d)"
                      prov={demandField("sold_count_30d")}
                      value={soldCount30d}
                    />
                  )}
                  <Metric
                    label="Avg sold price"
                    prov={demandField("avg_sold_price")}
                    value={
                      demand?.avg_sold_price != null
                        ? formatGBP(demand.avg_sold_price)
                        : "Not stated"
                    }
                  />
                  <Metric
                    label="Sold price range"
                    prov={demandField("price_range", "lowest_sold_price")}
                    value={soldRange}
                  />
                </div>

                {/* Only a purchase-history capture can produce a sale price, so
                  this sentence is a statement about where the numbers above
                  come from, not decoration. */}
                <p className="mt-3 text-[12px] leading-relaxed text-text-dim">
                  {saleVerified
                    ? "Read by the capture extension from your own eBay purchase history, in your own signed-in session. Not modelled, not estimated, and not a count of live listings."
                    : "This row holds a sales figure without recording which source produced it, so it is shown as unverified rather than given a source it did not name."}
                </p>

                {/* A3 — the observations behind the tiles above. Plotted from
                  the SAME list that produced them, so the shape of the market is
                  shown rather than asserted by a min/avg/max triple. Runs saved
                  before sold_prices existed render nothing here. */}
                {demand?.sold_prices && demand.sold_prices.length > 0 && (
                  <figure className="mt-4 rounded-card border border-border/50 bg-bg-surface/40 p-4">
                    <figcaption className="mb-3 flex items-baseline gap-3">
                      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
                        Sold price distribution
                      </span>
                      <span className="h-px flex-1 bg-border/40" />
                      <span className="text-[11px] text-text-dim">
                        {demand.sold_prices.length} observed sales
                      </span>
                    </figcaption>
                    <SoldPriceDistribution
                      prices={demand.sold_prices}
                      average={demand.avg_sold_price}
                    />
                  </figure>
                )}
              </div>
            )}

            {/* SUPPLY, and named as such — and, since PHASE C, named as the
              search-page count it actually is. These are asking prices on
              listings that are still for sale: nothing in this block sold. Every
              figure is real and was read from eBay, which is exactly why it must
              not sit under a "sold" heading: it did until 2026-10-19, and a
              listing price is not evidence of a sale however many of them there
              are. */}
            {hasActive && (
              <div className={hasSaleEvidence ? "mt-5" : ""}>
                <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
                    Search-page count
                  </span>
                  <span className="h-px flex-1 bg-border/40" />
                  <span className="text-[11px] text-text-dim">
                    supply, not sales
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Metric
                    label="In-band New listings"
                    prov={demandField("active_listings_in_band")}
                    value={demand?.active_listings_in_band ?? 0}
                  />
                  <Metric
                    label="Avg asking price"
                    prov={demandField("avg_active_price")}
                    value={
                      demand?.avg_active_price != null
                        ? formatGBP(demand.avg_active_price)
                        : "Not stated"
                    }
                  />
                  <Metric
                    label="Asking range"
                    prov={demandField("lowest_active_price")}
                    value={activeRange}
                  />
                </div>

                {demand?.active_prices && demand.active_prices.length > 0 && (
                  <figure className="mt-4 rounded-card border border-border/50 bg-bg-surface/40 p-4">
                    <figcaption className="mb-3 flex items-baseline gap-3">
                      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
                        Asking price distribution
                      </span>
                      <span className="h-px flex-1 bg-border/40" />
                      <span className="text-[11px] text-text-dim">
                        {demand.active_prices.length} live listings
                      </span>
                    </figcaption>
                    <SoldPriceDistribution
                      prices={demand.active_prices}
                      average={demand.avg_active_price}
                    />
                  </figure>
                )}
              </div>
            )}

            {/* Shown whenever a search count is what the reader is looking at,
              and only then: with a verified sale above it, the number has an
              owner and needs no disclaimer. */}
            {sale.showsSearchCountNote && <NoSalesTotalNote className="mt-4" />}
          </>
        ) : (
          <div className="rounded-card border border-border/50 border-dashed bg-bg-surface/30 px-5 py-8 text-center">
            <p className="text-sm font-medium text-text-secondary">
              No eBay evidence stored for this product
            </p>
            <p className="mt-2 mx-auto max-w-xl text-[13px] leading-relaxed text-text-dim">
              No search-page count and no sales reading were recorded for this
              product. A sale can only be verified from your own eBay purchase
              history, which the capture extension reads in your own signed-in
              session — nothing here estimates one instead.
            </p>
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* AI narrative — clearly separated from the facts above          */}
      {/* ---------------------------------------------------------------- */}
      {llmAnalysis && (
        <section>
          <SectionTitle hint="model opinion, not measurement">
            AI read
          </SectionTitle>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-3">
              <LlmLine
                label="Brand"
                value={llmAnalysis.brand_verdict}
                reasoning={llmAnalysis.brand_reasoning}
              />
              <LlmLine
                label="Demand"
                value={llmAnalysis.demand_assessment}
                reasoning={llmAnalysis.demand_reasoning}
              />
            </div>
            <div className="space-y-3">
              <LlmLine label="Action" value={llmAnalysis.recommended_action} />
              {llmAnalysis.supplier_type_reasoning && (
                <div className="rounded-card border border-border/40 bg-bg-surface/40 px-4 py-3">
                  <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-dim">
                    Supplier type
                  </span>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-text-secondary">
                    {llmAnalysis.supplier_type_reasoning}
                  </p>
                </div>
              )}
            </div>
          </div>
          {llmAnalysis.raw_response && (
            <details className="group mt-4">
              <summary className="cursor-pointer list-none text-[13px] text-text-dim transition-colors duration-200 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand-lime">
                <span className="group-open:hidden">
                  Show raw model response
                </span>
                <span className="hidden group-open:inline">
                  Hide raw model response
                </span>
              </summary>
              <pre className="mt-2 overflow-x-auto rounded-card border border-border/50 bg-bg-primary p-3 font-mono text-[11px] leading-relaxed text-text-secondary">
                {llmAnalysis.raw_response}
              </pre>
            </details>
          )}
        </section>
      )}

      {scorecard && (
        <details className="group">
          <summary className="cursor-pointer list-none rounded-card border border-border/40 px-4 py-3 text-sm text-text-secondary transition-colors duration-200 hover:border-border/70 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand-lime">
            <span className="group-open:hidden">
              Show full written scorecard
            </span>
            <span className="hidden group-open:inline">
              Hide written scorecard
            </span>
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-card border border-border/50 bg-bg-primary p-4 font-mono text-xs leading-relaxed text-text-secondary">
            {scorecard}
          </pre>
        </details>
      )}
    </div>
  );
}
