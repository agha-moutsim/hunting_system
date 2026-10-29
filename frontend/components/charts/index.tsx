"use client";

import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { currencySymbol, formatMoney } from "@/lib/format";
import { bucketPrices, distributionView } from "@/lib/buckets";
import { infoTitle } from "@/lib/provenance";
import type { ProvenanceInfo } from "@/lib/types";
import ProvenanceBadge from "@/components/ui/ProvenanceBadge";

const COLORS = [
  "#0D1CC4",
  "#CBFD03",
  "#BEC97D",
  "#8A90A0",
  "#FF5C5C",
  "#FFC857",
];

const tooltipStyle = {
  background: "#312C4D",
  border: "1px solid #4B525E",
  borderRadius: 8,
  color: "#FFFFFF",
  fontSize: 12,
};

export function TrendLine({
  data,
  xKey = "date",
  yKey = "value",
  color = "#0D1CC4",
  height = 240,
}: {
  data: Record<string, string | number>[];
  xKey?: string;
  yKey?: string;
  color?: string;
  height?: number;
}) {
  if (!data.length) {
    return (
      <div className="h-40 flex items-center justify-center text-sm text-text-dim">
        No chart data yet
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid
          stroke="#4B525E"
          strokeOpacity={0.3}
          strokeDasharray="3 3"
        />
        <XAxis dataKey={xKey} stroke="#8A90A0" fontSize={11} />
        <YAxis stroke="#8A90A0" fontSize={11} />
        <Tooltip contentStyle={tooltipStyle} />
        <Line
          type="monotone"
          dataKey={yKey}
          stroke={color}
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function RevenueProfitChart({
  labels,
  revenue,
  profit,
}: {
  labels: string[];
  revenue: number[];
  profit: (number | null)[];
}) {
  const data = labels.map((l, i) => ({
    month: l,
    revenue: revenue[i] ?? 0,
    // A null profit is unknown, not zero. Recharts leaves a gap rather than
    // drawing a bar that would claim the month made no money.
    profit: profit[i] ?? null,
  }));
  if (!data.length) {
    return (
      <div className="h-40 flex items-center justify-center text-sm text-text-dim">
        No monthly data yet
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data}>
        <CartesianGrid
          stroke="#4B525E"
          strokeOpacity={0.3}
          strokeDasharray="3 3"
        />
        <XAxis dataKey="month" stroke="#8A90A0" fontSize={11} />
        <YAxis stroke="#8A90A0" fontSize={11} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="revenue" fill="#0D1CC4" radius={[4, 4, 0, 0]} />
        <Bar dataKey="profit" fill="#CBFD03" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * A3 — the distribution of real sold prices for ONE product.
 *
 * Every bar is counted from `prices`, the exact list the eBay sold query
 * returned, which is also what produced the min/avg/max tiles above it. The
 * caption recomputes the average from that same list rather than taking a
 * second number from elsewhere, so the chart and the metric cannot disagree.
 *
 * Fewer than two observations means there is nothing to distribute: the
 * component says so instead of drawing a single bar that reads as a market.
 */
/**
 * The distribution of real sold prices for ONE product.
 *
 * Every bar is counted from `prices`, the exact list the eBay sold query
 * returned, which is also what produced the min/avg/max tiles beside it. The
 * caption recomputes the average from that same list rather than taking a
 * second number from elsewhere, so the chart and the metric cannot disagree.
 *
 * Fewer than two observations means there is nothing to distribute: the
 * component says so instead of drawing a single bar that reads as a market.
 *
 * `stamps` is optional, so a surface with no per-field provenance map renders
 * the caption bare rather than wearing a badge invented for it. Deep Search
 * supplies them because C13 says the label travels with the number.
 */
export function SoldPriceDistribution({
  prices,
  average,
  stamps,
  currency = "GBP",
}: {
  prices?: number[] | null;
  average?: number | null;
  stamps?: {
    count?: ProvenanceInfo;
    avg?: ProvenanceInfo;
    range?: ProvenanceInfo;
  };
  currency?: string;
}) {
  const view = distributionView(prices);

  if (view.kind === "empty") {
    return (
      <div className="h-32 flex items-center justify-center text-sm text-text-dim text-center px-4">
        {view.message}
      </div>
    );
  }

  const { observed, min, max, span } = view;
  const avg = average ?? observed.reduce((a, b) => a + b, 0) / observed.length;

  const data = bucketPrices(observed).map(({ range, count }) => ({
    range,
    count,
  }));

  const badge = (stamp?: ProvenanceInfo) =>
    stamp ? (
      <ProvenanceBadge
        provenance={stamp.provenance}
        label={stamp.label}
        title={infoTitle(stamp)}
      />
    ) : null;

  return (
    <div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={data}
          margin={{ top: 8, right: 8, left: -12, bottom: 4 }}
        >
          <CartesianGrid
            stroke="#4B525E"
            strokeOpacity={0.3}
            strokeDasharray="3 3"
          />
          <XAxis dataKey="range" stroke="#8A90A0" fontSize={11} />
          <YAxis stroke="#8A90A0" fontSize={11} allowDecimals={false} />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: number | string) => [String(value), "Sales"]}
            labelFormatter={(label: string | number) =>
              `${currencySymbol(currency)}${label}`
            }
          />
          <Bar dataKey="count" fill="#0D1CC4" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-text-dim mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <span className="inline-flex items-center gap-1">
          {observed.length} observed sale{observed.length === 1 ? "" : "s"}
          {badge(stamps?.count)}
        </span>
        <span aria-hidden="true">·</span>
        <span className="inline-flex items-center gap-1">
          avg {formatMoney(avg, currency)}
          {badge(stamps?.avg)}
        </span>
        <span aria-hidden="true">·</span>
        <span className="inline-flex items-center gap-1">
          range {formatMoney(min, currency)}–{formatMoney(max, currency)}
          {badge(stamps?.range)}
        </span>
        {span === 0 && <span>all sales at one price</span>}
      </p>
    </div>
  );
}

export function CategoryPie({
  categories,
  values,
}: {
  categories: string[];
  values: number[];
}) {
  const data = categories.map((c, i) => ({
    name: c || "Uncategorised",
    value: values[i] || 0,
  }));
  if (!data.length || data.every((d) => d.value === 0)) {
    return (
      <div className="h-40 flex items-center justify-center text-sm text-text-dim">
        No category data yet
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius={90}
          label={({ name, percent }) =>
            `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
          }
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip contentStyle={tooltipStyle} />
      </PieChart>
    </ResponsiveContainer>
  );
}
