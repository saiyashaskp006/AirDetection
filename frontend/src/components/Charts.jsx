import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const series = [
  { key: "temperature", label: "Temperature", color: "#59d9ae", unit: "°C" },
  { key: "co_ppm", label: "CO", color: "#58b8ff", unit: " ppm" },
  { key: "mq135_raw", label: "MQ-135", color: "#b69aff", unit: " V" },
  { key: "dust_ug_m3", label: "Dust", color: "#f6bd60", unit: " µg/m³" },
];

export function TrendChart({ data, compact = false }) {
  const first = data.length ? new Date(data[0].timestamp).getTime() : 0;
  const last = data.length ? new Date(data[data.length - 1].timestamp).getTime() : 0;
  const withSeconds = data.length > 1 ? last - first <= 10 * 60 * 1000 : true;
  const chartData = data.map((item) => ({
    ...item,
    time: new Date(item.timestamp).toLocaleTimeString([], withSeconds
      ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" }),
  }));
  return (
    <div className={compact ? "chart chart-compact" : "chart"}>
      {!chartData.length ? (
        <div className="empty-chart">Sensor readings will appear here as data arrives.</div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#1b2b3a" strokeDasharray="3 5" vertical={false} />
            <XAxis dataKey="time" tick={{ fill: "#8294a8", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={30} />
            <YAxis tick={{ fill: "#8294a8", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: "#101e2c", border: "1px solid #26394b", borderRadius: 10, color: "#e8f1f8" }}
              labelStyle={{ color: "#9cb0c3" }}
            />
            <Legend wrapperStyle={{ color: "#9cb0c3", fontSize: 11 }} />
            {series.map((item) => (
              <Line
                key={item.key}
                type="monotone"
                dataKey={item.key}
                name={`${item.label}${item.unit}`}
                stroke={item.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export function SingleTrend({ data, dataKey, color, unit }) {
  return (
    <div className="mini-chart">
      {data.length > 1 ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <Tooltip
              contentStyle={{ background: "#101e2c", border: "1px solid #26394b", borderRadius: 8, color: "#e8f1f8" }}
              formatter={(value) => [`${value ?? "—"}${unit}`, "Reading"]}
              labelFormatter={(value) => new Date(value).toLocaleTimeString()}
            />
            <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      ) : <span className="chart-placeholder">Awaiting readings</span>}
    </div>
  );
}
