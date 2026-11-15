import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const SPIKE_WINDOW_MS = 3_000;
const SPIKE_WINDOW_MAX_MS = 120_000;
const SPIKE_MAX_DURATION_MS = 3_000;
const SPIKE_RUN_MAX_MS = 60_000;
const SPIKE_SIGMA = 6;

export const CHART_SERIES = [
  { key: "temperature", label: "Temperature", short: "Temp", color: "#59d9ae", unit: "°C", digits: 1, spikeFloor: 2 },
  { key: "pressure", label: "Pressure", short: "Pressure", color: "#5fd0e6", unit: " hPa", digits: 0, spikeFloor: 5 },
  { key: "co_ppm", label: "Carbon monoxide", short: "CO", color: "#58b8ff", unit: " ppm", digits: 2, spikeFloor: 5 },
  { key: "mq135_estimated_ppm", label: "MQ-135 estimate", short: "MQ-135", color: "#b69aff", unit: " ppm", digits: 0, spikeFloor: 30 },
  { key: "dust_ug_m3", label: "Dust estimate", short: "Dust", color: "#f6bd60", unit: " µg/m³", digits: 1, spikeFloor: 30 },
];

const seriesByKey = Object.fromEntries(CHART_SERIES.map((item) => [item.key, item]));

function numeric(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function timestampOf(row) {
  const timestamp = new Date(row?.timestamp).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * Sort, de-duplicate, and add a numeric `ts` field for Recharts. This prevents
 * duplicate/out-of-order timestamps from drawing loops or jumps in the line.
 */
function normalizeData(data) {
  const byTimestamp = new Map();
  for (const row of data || []) {
    const ts = timestampOf(row);
    if (ts == null) continue;
    byTimestamp.set(ts, { ...(byTimestamp.get(ts) || {}), ...row, ts });
  }
  return [...byTimestamp.values()].sort((a, b) => a.ts - b.ts);
}

/**
 * Display-only despiker. A centred median/MAD window flags isolated short
 * transient runs; the allowed run length scales with the sampled interval so
 * downsampled history is handled too. The returned rows are copies; no
 * stored/API data is changed.
 */
function filterSpikeValues(data, key, floor) {
  if (!data.length) return { rows: data, hidden: 0 };
  const points = data.map((row, index) => ({ index, ts: row.ts, value: numeric(row[key]) }));
  const valid = points.filter((point) => point.value != null);
  if (valid.length < 4) return { rows: data, hidden: 0 };

  const intervals = [];
  for (let index = 1; index < valid.length; index += 1) {
    const gap = valid[index].ts - valid[index - 1].ts;
    if (gap > 0) intervals.push(gap);
  }
  const sampleInterval = median(intervals) || 1_000;
  const windowMs = Math.min(SPIKE_WINDOW_MAX_MS, Math.max(SPIKE_WINDOW_MS, sampleInterval * 12));

  let left = 0;
  let right = 0;
  const flags = [];
  for (let index = 0; index < valid.length; index += 1) {
    const point = valid[index];
    while (left < index && valid[left].ts < point.ts - windowMs) left += 1;
    right = Math.max(right, index);
    while (right + 1 < valid.length && valid[right + 1].ts <= point.ts + windowMs) right += 1;

    const neighbours = valid.slice(left, right + 1).map((item) => item.value);
    if (neighbours.length < 3) {
      flags.push(false);
      continue;
    }
    const localMedian = median(neighbours);
    const mad = median(neighbours.map((value) => Math.abs(value - localMedian)));
    const threshold = Math.max(floor, SPIKE_SIGMA * 1.4826 * mad, Math.abs(localMedian) * 0.03);
    flags.push(Math.abs(point.value - localMedian) > threshold);
  }

  const runs = [];
  let currentRun = null;
  for (let index = 0; index < valid.length; index += 1) {
    if (!flags[index]) continue;
    const point = valid[index];
    if (
      currentRun
      && point.ts - currentRun.points[currentRun.points.length - 1].ts > Math.max(1_500, sampleInterval * 2.5)
    ) {
      currentRun = null;
    }
    if (!currentRun) {
      currentRun = { start: index, end: index, points: [] };
      runs.push(currentRun);
    }
    currentRun.end = index;
    currentRun.points.push(point);
  }

  const maxRunDuration = Math.min(
    SPIKE_RUN_MAX_MS,
    Math.max(SPIKE_MAX_DURATION_MS, sampleInterval * 10) + sampleInterval * 1.5,
  );
  const hiddenIndexes = new Set();
  for (const run of runs) {
    const duration = run.points[run.points.length - 1].ts - run.points[0].ts;
    if (duration > maxRunDuration) continue;

    // Only hide a burst that returns to roughly the same baseline. A real
    // sustained step change (before and after levels differ) is left alone.
    const before = median(
      valid.slice(Math.max(0, run.start - 5), run.start).map((point) => point.value),
    );
    const after = median(
      valid.slice(run.end + 1, Math.min(valid.length, run.end + 6)).map((point) => point.value),
    );
    if (before != null && after != null) {
      const tolerance = Math.max(floor * 2, Math.abs(before) * 0.2, Math.abs(after) * 0.2);
      if (Math.abs(before - after) > tolerance) continue;
    }
    run.points.forEach((point) => hiddenIndexes.add(point.index));
  }

  if (!hiddenIndexes.size) return { rows: data, hidden: 0 };
  return {
    rows: data.map((row, index) => hiddenIndexes.has(index) ? { ...row, [key]: null } : row),
    hidden: hiddenIndexes.size,
  };
}

function formatNumber(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatFullTime(timestamp) {
  if (!Number.isFinite(Number(timestamp))) return "";
  return new Date(Number(timestamp)).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
}

function formatAxisTick(timestamp, span) {
  const date = new Date(Number(timestamp));
  if (!Number.isFinite(date.getTime())) return "";
  if (span > 2 * 24 * 60 * 60 * 1000) {
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  if (span > 60 * 60 * 1000) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const items = payload.filter((item) => item.value != null);
  if (!items.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-time">{formatFullTime(label)}</div>
      {items.map((item) => {
        const spec = seriesByKey[item.dataKey];
        return (
          <div className="chart-tooltip-row" key={item.dataKey}>
            <i style={{ background: item.color || spec?.color }} />
            <span>{spec?.label || item.name}</span>
            <strong>{formatNumber(item.value, spec?.digits ?? 1)}{spec?.unit || ""}</strong>
          </div>
        );
      })}
    </div>
  );
}

export function TrendChart({ data, compact = false }) {
  const [selectedKey, setSelectedKey] = useState("all");
  const [hideSpikes, setHideSpikes] = useState(true);
  const normalized = useMemo(() => normalizeData(data), [data]);

  const filtered = useMemo(() => {
    if (!hideSpikes) return { rows: normalized, hidden: 0 };
    const keys = selectedKey === "all" ? CHART_SERIES.map((item) => item.key) : [selectedKey];
    let rows = normalized;
    let hidden = 0;
    for (const key of keys) {
      const result = filterSpikeValues(rows, key, seriesByKey[key]?.spikeFloor ?? 0);
      rows = result.rows;
      hidden += result.hidden;
    }
    return { rows, hidden };
  }, [normalized, selectedKey, hideSpikes]);

  const visibleSeries = selectedKey === "all" ? CHART_SERIES : CHART_SERIES.filter((item) => item.key === selectedKey);
  const chartData = filtered.rows;
  const span = chartData.length > 1 ? chartData[chartData.length - 1].ts - chartData[0].ts : 0;
  const hasData = chartData.some((row) => visibleSeries.some((item) => numeric(row[item.key]) != null));
  const hasRawData = normalized.some((row) => visibleSeries.some((item) => numeric(row[item.key]) != null));
  const onlySeries = selectedKey === "all" ? null : seriesByKey[selectedKey];
  const singlePoint = chartData.length === 1;

  return (
    <div className={`trend-chart-block${compact ? " compact" : ""}`}>
      <div className="chart-toolbar">
        <div className="chart-series-tabs" role="tablist" aria-label="Sensor series">
          {CHART_SERIES.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={selectedKey === item.key}
              className={`chart-series-tab${selectedKey === item.key ? " selected" : ""}`}
              onClick={() => setSelectedKey(item.key)}
            >
              <i style={{ background: item.color }} />
              {item.short}
            </button>
          ))}
          <button
            type="button"
            role="tab"
            aria-selected={selectedKey === "all"}
            className={`chart-series-tab${selectedKey === "all" ? " selected" : ""}`}
            onClick={() => setSelectedKey("all")}
          >
            All
          </button>
        </div>
        <div className="chart-toolbar-right">
          <span className="chart-axis-note">{onlySeries ? `${onlySeries.label} · ${onlySeries.unit.trim()}` : "Mixed units"}</span>
          <label className="spike-toggle" title="Display-only: isolated short transients are hidden. Stored data is not changed.">
            <input type="checkbox" checked={hideSpikes} onChange={(event) => setHideSpikes(event.target.checked)} />
            Hide transient spikes
          </label>
        </div>
      </div>

      <div className={compact ? "chart chart-compact" : "chart"}>
        {!hasData ? (
          <div className="empty-chart">
            {hasRawData
              ? `All ${onlySeries?.label || "sensor"} readings in this period looked like transient spikes. Turn off “Hide transient spikes” to view them.`
              : `No ${onlySeries?.label || "sensor"} readings in this period.`}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 12, left: compact ? -16 : 0, bottom: 0 }}>
              <CartesianGrid stroke="#1b2b3a" strokeDasharray="3 5" vertical={false} />
              <XAxis
                dataKey="ts"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tick={{ fill: "#8294a8", fontSize: 11 }}
                tickFormatter={(value) => formatAxisTick(value, span)}
                axisLine={false}
                tickLine={false}
                minTickGap={compact ? 50 : 34}
                tickMargin={7}
              />
              <YAxis
                tick={{ fill: "#8294a8", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={compact ? 34 : 48}
                tickFormatter={(value) => formatNumber(value, onlySeries?.digits ?? 1)}
                label={onlySeries ? { value: onlySeries.unit.trim(), angle: -90, position: "insideLeft", fill: "#8294a8", fontSize: 10 } : undefined}
                tickMargin={4}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#33516a", strokeDasharray: "4 4" }} />
              {visibleSeries.map((item) => (
                <Line
                  key={item.key}
                  type="linear"
                  dataKey={item.key}
                  name={item.label}
                  stroke={item.color}
                  strokeWidth={selectedKey === "all" ? 1.6 : 2.2}
                  dot={singlePoint ? { r: 3, strokeWidth: 0, fill: item.color } : false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="chart-display-note">
        {hideSpikes
          ? `Display only: isolated short transients are hidden${filtered.hidden ? ` (${filtered.hidden} point${filtered.hidden === 1 ? "" : "s"})` : ""}. At 1 Hz this targets roughly 1–3 s; downsampled history spans longer. Stored readings are unchanged.`
          : "Displaying raw points. Stored readings are unchanged."}
      </div>
    </div>
  );
}

export function SingleTrend({ data, dataKey, color, unit }) {
  const spec = seriesByKey[dataKey];
  const rows = useMemo(() => {
    const normalized = normalizeData(data);
    return filterSpikeValues(normalized, dataKey, spec?.spikeFloor ?? 0).rows;
  }, [data, dataKey, spec?.spikeFloor]);
  const hasData = rows.filter((row) => numeric(row[dataKey]) != null).length > 1;

  return (
    <div className="mini-chart">
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows}>
            <XAxis dataKey="ts" type="number" hide />
            <YAxis hide domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={{ background: "#101e2c", border: "1px solid #26394b", borderRadius: 8, color: "#e8f1f8" }}
              formatter={(value) => [`${formatNumber(value, spec?.digits ?? 1)}${unit}`, spec?.label || "Reading"]}
              labelFormatter={(value) => formatFullTime(value)}
            />
            <Line
              type="linear"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : <span className="chart-placeholder">Awaiting readings</span>}
    </div>
  );
}
