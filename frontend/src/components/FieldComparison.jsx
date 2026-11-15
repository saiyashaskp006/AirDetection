import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CalendarRange, CircleAlert, Clock3, Download, MapPin, Plus, RefreshCw, Trash2,
} from "lucide-react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CHART_SERIES } from "./Charts";
import { LocationMap } from "./LocationMap";
import { api } from "../services/api";

const STORAGE_KEY = "aerohub-field-sessions-v1";
const SESSION_COLORS = ["#59d9ae", "#58b8ff", "#f6bd60", "#b69aff", "#ff8e8e", "#5fd0e6"];
const EMPTY_FORM = { name: "", latitude: "", longitude: "", start: "", end: "" };

const number = (value) => {
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
};

const median = (values) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

const fmt = (value, digits = 1) => value == null || !Number.isFinite(Number(value))
  ? "—"
  : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });

const stamp = (value) => value
  ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
  : "—";

const durationMinutes = (session) => {
  const milliseconds = new Date(session.end).getTime() - new Date(session.start).getTime();
  return Number.isFinite(milliseconds) ? Math.max(0, Math.round(milliseconds / 60_000)) : 0;
};

const toLocalInput = (date) => {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const sampleCount = (session) => Math.max(
  0,
  ...Object.values(session.stats || {}).map((stat) => Number(stat?.count) || 0),
);

const csvCell = (value) => JSON.stringify(value ?? "");

function readStoredSessions() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((session) => session
        && session.id
        && session.name
        && Number.isFinite(new Date(session.start).getTime())
        && Number.isFinite(new Date(session.end).getTime())
        && Number.isFinite(Number(session.latitude))
        && Number.isFinite(Number(session.longitude)))
      .map((session) => ({
        ...session,
        latitude: Number(session.latitude),
        longitude: Number(session.longitude),
        rows: [],
        stats: null,
        loading: true,
        error: "",
      }));
  } catch {
    return [];
  }
}

function saveStoredSessions(sessions) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.map((session) => ({
      id: session.id,
      name: session.name,
      latitude: session.latitude,
      longitude: session.longitude,
      start: session.start,
      end: session.end,
    }))));
  } catch {
    // Private browsing can make localStorage unavailable. The page still works
    // for the current tab; only the saved session list is lost on reload.
  }
}

function buildComparisonData(sessions, metric) {
  const visible = sessions
    .filter((session) => session.rows?.length && !session.error)
    .map((session) => ({
      session,
      color: SESSION_COLORS[sessions.indexOf(session) % SESSION_COLORS.length],
    }));

  if (!visible.length) return { rows: [], series: [], maxElapsed: 0 };

  const maxElapsed = Math.max(
    1,
    ...visible.map(({ session }) => Math.ceil(
      Math.max(0, new Date(session.end).getTime() - new Date(session.start).getTime()) / 60_000,
    )),
  );
  const rows = Array.from({ length: maxElapsed + 1 }, (_, elapsed) => ({ elapsed }));
  const series = visible.map(({ session, color }, index) => ({
    key: `s${index}`,
    sessionId: session.id,
    name: session.name,
    color,
  }));

  visible.forEach(({ session }, index) => {
    const start = new Date(session.start).getTime();
    if (!Number.isFinite(start)) return;
    const buckets = Array.from({ length: maxElapsed + 1 }, () => []);
    for (const row of session.rows) {
      const value = number(row[metric.key]);
      if (value == null) continue;
      const timestamp = new Date(row.timestamp).getTime();
      if (!Number.isFinite(timestamp)) continue;
      const elapsed = Math.floor((timestamp - start) / 60_000);
      if (elapsed < 0 || elapsed > maxElapsed) continue;
      buckets[elapsed].push(value);
    }
    buckets.forEach((values, elapsed) => {
      if (values.length) rows[elapsed][`s${index}`] = median(values);
    });
  });

  return { rows, series, maxElapsed };
}

function ComparisonTooltip({ active, payload, label, series, metric }) {
  if (!active || !payload?.length) return null;
  const items = payload.filter((item) => item.value != null);
  if (!items.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-time">Elapsed {Math.round(label)} min</div>
      {items.map((item) => {
        const itemSeries = series.find((entry) => entry.key === item.dataKey);
        return (
          <div className="chart-tooltip-row" key={item.dataKey}>
            <i style={{ background: itemSeries?.color || item.color }} />
            <span>{itemSeries?.name || item.name}</span>
            <strong>{fmt(item.value, metric.digits)}{metric.unit}</strong>
          </div>
        );
      })}
    </div>
  );
}

function Field({ label, unit, value, onChange, type = "text", ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="input-with-unit">
        <input type={type} value={value} onChange={(event) => onChange(event.target.value)} {...props} />
        {unit ? <i>{unit}</i> : null}
      </div>
    </label>
  );
}

export function FieldComparison({ notify }) {
  const [sessions, setSessions] = useState(readStoredSessions);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [selectedMetricKey, setSelectedMetricKey] = useState("dust_ug_m3");
  const [selectedCenter, setSelectedCenter] = useState(null);
  const hydrated = useRef(false);

  const selectedMetric = CHART_SERIES.find((metric) => metric.key === selectedMetricKey) || CHART_SERIES[0];
  const comparison = useMemo(
    () => buildComparisonData(sessions, selectedMetric),
    [sessions, selectedMetric],
  );

  const refreshSession = useCallback(async (session) => {
    setSessions((current) => current.map((item) => item.id === session.id
      ? { ...item, loading: true, error: "" }
      : item));
    try {
      const range = `start=${encodeURIComponent(session.start)}&end=${encodeURIComponent(session.end)}`;
      const [rows, stats] = await Promise.all([
        api(`/api/sensors/history?${range}&limit=50000&max_points=2000`),
        api(`/api/sensors/statistics?${range}`),
      ]);
      setSessions((current) => current.map((item) => item.id === session.id
        ? { ...item, rows, stats, loading: false, error: rows.length ? "" : "No readings found in this time range." }
        : item));
    } catch (reason) {
      setSessions((current) => current.map((item) => item.id === session.id
        ? { ...item, rows: [], stats: null, loading: false, error: reason.message }
        : item));
    }
  }, []);

  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    sessions.forEach((session) => { refreshSession(session); });
  }, [refreshSession, sessions]);

  useEffect(() => {
    saveStoredSessions(sessions);
  }, [sessions]);

  const change = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const useStandardDuration = () => {
    const start = form.start ? new Date(form.start) : new Date();
    if (!Number.isFinite(start.getTime())) {
      setFormError("Enter a valid start time first.");
      return;
    }
    const end = new Date(start.getTime() + 45 * 60_000);
    setForm((current) => ({
      ...current,
      start: current.start || toLocalInput(start),
      end: toLocalInput(end),
    }));
  };

  const addSession = (event) => {
    event.preventDefault();
    setFormError("");
    const name = form.name.trim();
    const latitude = number(form.latitude);
    const longitude = number(form.longitude);
    const start = new Date(form.start);
    const end = new Date(form.end);

    if (!name) return setFormError("Enter a site name.");
    if (form.latitude.trim() === "" || form.longitude.trim() === "") {
      return setFormError("Enter both latitude and longitude.");
    }
    if (latitude == null || latitude < -90 || latitude > 90) {
      return setFormError("Latitude must be between -90 and 90.");
    }
    if (longitude == null || longitude < -180 || longitude > 180) {
      return setFormError("Longitude must be between -180 and 180.");
    }
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
      return setFormError("Enter a valid beginning and end time.");
    }
    if (end.getTime() <= start.getTime()) {
      return setFormError("End time must be after the beginning time.");
    }

    const session = {
      id: window.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      name,
      latitude,
      longitude,
      start: start.toISOString(),
      end: end.toISOString(),
    };
    setSessions((current) => [...current, {
      ...session, rows: [], stats: null, loading: true, error: "",
    }]);
    setForm(EMPTY_FORM);
    notify?.(`${name} added. Loading readings…`);
    refreshSession(session);
    return undefined;
  };

  const removeSession = (id) => {
    setSessions((current) => current.filter((session) => session.id !== id));
    notify?.("Field session removed.");
  };

  const exportSummary = () => {
    if (!sessions.length) {
      notify?.("Add at least one field session before exporting.");
      return;
    }
    const metricColumns = CHART_SERIES.flatMap((metric) => [
      `${metric.key}_average`,
      `${metric.key}_max`,
    ]);
    const columns = [
      "site", "latitude", "longitude", "start_utc", "end_utc",
      "duration_minutes", "samples", ...metricColumns,
    ];
    const lines = sessions.map((session) => {
      const values = [
        session.name,
        session.latitude,
        session.longitude,
        session.start,
        session.end,
        durationMinutes(session),
        sampleCount(session),
        ...CHART_SERIES.flatMap((metric) => {
          const stat = session.stats?.[metric.key];
          return [stat?.average ?? "", stat?.max ?? ""];
        }),
      ];
      return values.map(csvCell).join(",");
    });
    const blob = new Blob([[columns.join(","), ...lines].join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `aerohub-location-comparison-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    notify?.("Comparison summary exported.");
  };

  const mapLocations = sessions.map((session) => ({
    location_name: session.name,
    latitude: session.latitude,
    longitude: session.longitude,
    latest: null,
  }));

  const comparisonReady = sessions.some((session) => session.rows?.length && !session.error);
  const metricHasData = comparison.rows.some((row) => comparison.series.some(
    (item) => row[item.key] != null,
  ));

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">FIELD CAMPAIGNS</div>
          <h1>Location comparison</h1>
          <p>Record a time window for each site, then compare the readings from the same field campaign.</p>
        </div>
        <div className="heading-actions">
          <button className="secondary-button" onClick={exportSummary} disabled={!sessions.length}>
            <Download size={15} /> Export summary
          </button>
        </div>
      </div>

      <article className="panel field-form-panel">
        <div className="panel-heading">
          <div>
            <h2>Add a field session</h2>
            <p>Readings are queried from the database by this time range; the coordinates label the site.</p>
          </div>
          <span className="field-form-note"><MapPin size={14} /> Stored in this browser</span>
        </div>
        <form onSubmit={addSession}>
          <div className="form-grid field-form-grid">
            <Field label="Site name" unit="" value={form.name} onChange={(value) => change("name", value)} maxLength="120" placeholder="e.g. North campus" />
            <Field label="Latitude" unit="°" value={form.latitude} onChange={(value) => change("latitude", value)} type="number" min="-90" max="90" step="any" placeholder="e.g. 28.6139" />
            <Field label="Longitude" unit="°" value={form.longitude} onChange={(value) => change("longitude", value)} type="number" min="-180" max="180" step="any" placeholder="e.g. 77.2090" />
            <label className="field">
              <span>Beginning time</span>
              <input type="datetime-local" value={form.start} onChange={(event) => change("start", event.target.value)} />
            </label>
            <label className="field">
              <span>End time</span>
              <input type="datetime-local" value={form.end} onChange={(event) => change("end", event.target.value)} />
            </label>
            <div className="field field-duration">
              <span>Recording length</span>
              <button type="button" className="secondary-button" onClick={useStandardDuration}>
                <Clock3 size={14} /> Set 45 minutes
              </button>
            </div>
          </div>
          {formError && <div className="inline-error">{formError}</div>}
          <div className="form-footer">
            <span><CircleAlert size={14} /> Session definitions stay in this browser; raw readings remain in the database.</span>
            <button className="primary-button" type="submit"><Plus size={16} /> Add and load session</button>
          </div>
        </form>
      </article>

      {!sessions.length ? (
        <div className="panel field-empty-state">
          <MapPin size={28} />
          <h3>No field sessions yet</h3>
          <p>Add the first location above. Repeat for each of your four sites, then compare their readings here.</p>
        </div>
      ) : (
        <>
          <div className="field-session-grid">
            {sessions.map((session, index) => {
              const count = sampleCount(session);
              return (
                <article className="panel field-session-card" key={session.id}>
                  <div className="field-session-head">
                    <span className="field-session-index" style={{ background: SESSION_COLORS[index % SESSION_COLORS.length] }}>{index + 1}</span>
                    <div className="field-session-identity">
                      <strong>{session.name}</strong>
                      <span>{Number(session.latitude).toFixed(5)}, {Number(session.longitude).toFixed(5)}</span>
                    </div>
                    <button className="field-remove-button" onClick={() => removeSession(session.id)} aria-label={`Remove ${session.name}`} title="Remove session">
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <div className="field-session-time">
                    <CalendarRange size={14} />
                    <span>{stamp(session.start)}<br />to {stamp(session.end)}</span>
                  </div>
                  <div className="field-session-meta">
                    <span>{durationMinutes(session)} min</span>
                    <span>{session.loading ? "Loading…" : session.error ? "No data" : `${count} samples`}</span>
                  </div>
                  {session.error && <div className="field-session-error">{session.error}</div>}
                  <button className="secondary-button field-refresh-button" onClick={() => refreshSession(session)} disabled={session.loading}>
                    <RefreshCw size={13} /> {session.loading ? "Loading…" : "Refresh"}
                  </button>
                </article>
              );
            })}
          </div>

          {comparisonReady ? (
            <>
              <article className="panel field-chart-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Compare locations</h2>
                    <p>1-minute medians by elapsed time. Stored readings are unchanged.</p>
                  </div>
                  <span className="field-chart-unit">{selectedMetric.label} · {selectedMetric.unit.trim()}</span>
                </div>
                <div className="chart-series-tabs field-metric-tabs" role="tablist" aria-label="Comparison metric">
                  {CHART_SERIES.map((metric) => (
                    <button
                      key={metric.key}
                      type="button"
                      role="tab"
                      aria-selected={selectedMetricKey === metric.key}
                      className={`chart-series-tab${selectedMetricKey === metric.key ? " selected" : ""}`}
                      onClick={() => setSelectedMetricKey(metric.key)}
                    >
                      <i style={{ background: metric.color }} />
                      {metric.short}
                    </button>
                  ))}
                </div>
                <div className="field-comparison-chart">
                  {metricHasData ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={comparison.rows} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke="#1b2b3a" strokeDasharray="3 5" vertical={false} />
                        <XAxis
                          dataKey="elapsed"
                          type="number"
                          domain={[0, comparison.maxElapsed]}
                          tick={{ fill: "#8294a8", fontSize: 11 }}
                          tickFormatter={(value) => `${Math.round(value)}m`}
                          axisLine={false}
                          tickLine={false}
                          minTickGap={28}
                          tickMargin={7}
                        />
                        <YAxis
                          tick={{ fill: "#8294a8", fontSize: 11 }}
                          axisLine={false}
                          tickLine={false}
                          width={50}
                          tickFormatter={(value) => fmt(value, selectedMetric.digits)}
                          label={{ value: selectedMetric.unit.trim(), angle: -90, position: "insideLeft", fill: "#8294a8", fontSize: 10 }}
                          tickMargin={4}
                        />
                        <Tooltip
                          content={<ComparisonTooltip series={comparison.series} metric={selectedMetric} />}
                          cursor={{ stroke: "#33516a", strokeDasharray: "4 4" }}
                        />
                        {comparison.series.map((item) => (
                          <Line
                            key={item.key}
                            type="linear"
                            dataKey={item.key}
                            name={item.name}
                            stroke={item.color}
                            strokeWidth={2}
                            dot={false}
                            activeDot={{ r: 4, strokeWidth: 0 }}
                            connectNulls
                            isAnimationActive={false}
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="field-chart-empty">No {selectedMetric.label.toLowerCase()} readings in these sessions.</div>
                  )}
                </div>
                <div className="field-chart-legend">
                  {comparison.series.map((item) => (
                    <span key={item.key}><i style={{ background: item.color }} />{item.name}</span>
                  ))}
                </div>
              </article>

              <article className="panel field-table-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Location summary</h2>
                    <p>Average and maximum from stored readings for each session.</p>
                  </div>
                  <span className="source-key"><i className="source-dot" /> Database</span>
                </div>
                <div className="field-table-wrap">
                  <table className="field-comparison-table">
                    <thead>
                      <tr>
                        <th>Location</th>
                        {CHART_SERIES.map((metric) => <th key={metric.key}>{metric.short}<small>{metric.unit.trim()}</small></th>)}
                        <th>Samples</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.map((session, index) => (
                        <tr key={session.id}>
                          <td>
                            <div className="field-table-site">
                              <i style={{ background: SESSION_COLORS[index % SESSION_COLORS.length] }} />
                              <span><strong>{session.name}</strong><small>{stamp(session.start)}</small></span>
                            </div>
                          </td>
                          {CHART_SERIES.map((metric) => {
                            const stat = session.stats?.[metric.key];
                            return (
                              <td key={metric.key}>
                                {stat?.count ? (
                                  <div className="field-metric-value">
                                    <strong>{fmt(stat.average, metric.digits)}</strong>
                                    <small>max {fmt(stat.max, metric.digits)}</small>
                                  </div>
                                ) : <span className="field-metric-empty">—</span>}
                              </td>
                            );
                          })}
                          <td>{session.loading ? "…" : session.error ? "0" : sampleCount(session)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </article>

              {mapLocations.length > 0 && (
                <article className="panel field-map-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Recorded sites</h2>
                      <p>Coordinates entered for each field session.</p>
                    </div>
                    <span className="count-pill">{mapLocations.length} sites</span>
                  </div>
                  <LocationMap
                    locations={mapLocations}
                    selectedCenter={selectedCenter}
                    onSelect={(latitude, longitude) => setSelectedCenter({ latitude, longitude })}
                  />
                </article>
              )}
            </>
          ) : (
            <div className="panel field-empty-state field-loading-state">
              <RefreshCw size={24} />
              <h3>Waiting for session readings</h3>
              <p>Add a valid time range or refresh a session to load its comparison data.</p>
            </div>
          )}
        </>
      )}
    </>
  );
}
