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
  profit: number[];
}) {
  const data = labels.map((l, i) => ({
    month: l,
    revenue: revenue[i] || 0,
    profit: profit[i] || 0,
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
