import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Check, ChevronDown, CircleAlert, Clock3,
  Cloud, Droplets, Gauge, Leaf, MapPin, Menu, Radio, RadioTower, RefreshCw, Thermometer, Wind,
} from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { MetricCard } from "./components/MetricCard";
import { TrendChart } from "./components/Charts";
import { LocationMap } from "./components/LocationMap";
import { useLiveData } from "./hooks/useLiveData";
import { api } from "./services/api";

const pages = {
  overview: "Air quality overview",
  live: "Live monitoring",
  analytics: "Historical analytics",
  manual: "Manual data entry",
  alerts: "Pollution alerts",
  sensors: "Sensor management",
  settings: "System settings",
};

const fmt = (value, digits = 1) => value == null ? null : Number(value).toFixed(digits);
const stamp = (value) => value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Waiting for first reading";
const scoreColor = (score) => score >= 80 ? "green" : score >= 60 ? "yellow" : score >= 35 ? "orange" : "red";

export default function App() {
  const [page, setPage] = useState(() => window.location.hash === "#dashboard" ? "overview" : "intro");
  const [menuOpen, setMenuOpen] = useState(false);
  const [toast, setToast] = useState("");
  const live = useLiveData();
  const seenAlertIds = useRef(new Set());
  const alertBaselineSet = useRef(false);
  const data = live.history;
  const latest = live.latest;

  useEffect(() => {
    if (!live.error) return undefined;
    setToast(live.error);
    const timer = window.setTimeout(() => setToast(""), 6000);
    return () => window.clearTimeout(timer);
  }, [live.error]);

  useEffect(() => {
    const syncPageFromUrl = () => {
      setPage(window.location.hash === "#dashboard" ? "overview" : "intro");
    };
    window.addEventListener("hashchange", syncPageFromUrl);
    return () => window.removeEventListener("hashchange", syncPageFromUrl);
  }, []);

  useEffect(() => {
    if (!alertBaselineSet.current) {
      live.alerts.forEach((alert) => seenAlertIds.current.add(alert.id));
      alertBaselineSet.current = true;
      return;
    }
    const newCritical = live.alerts.find(
      (alert) => alert.severity === "critical" && !seenAlertIds.current.has(alert.id),
    );
    live.alerts.forEach((alert) => seenAlertIds.current.add(alert.id));
    if (newCritical) setToast(`Critical ${newCritical.alert_type} alert: ${newCritical.message}`);
  }, [live.alerts]);

  const title = pages[page];
  const lastSeen = latest ? stamp(latest.timestamp) : "No readings received";
  const isDemo = latest?.source === "simulation";

  if (page === "intro") return <IntroPage />;

  return (
    <div className="app-shell">
      <Sidebar page={page} setPage={setPage} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <main className="main-area" id="dashboard">
        <header className="topbar">
          <button className="icon-button menu-button" aria-label="Open navigation" onClick={() => setMenuOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{title}</strong></div>
          <div className="topbar-right">
            {isDemo && <span className="demo-pill"><span /> DEMO DATA</span>}
            <span className={`connection-pill ${live.socketStatus}`}><span className="status-pip" />{live.socketStatus === "connected" ? "Live connected" : live.socketStatus === "connecting" ? "Connecting" : "Reconnecting"}</span>
            <button className="avatar" title="Monitoring station">AS</button>
          </div>
        </header>
        <div className="content">
          {page === "overview" && <Overview latest={latest} data={data} alerts={live.alerts} sensors={live.sensors} lastSeen={lastSeen} setPage={setPage} notify={setToast} />}
          {page === "live" && <LivePage data={data} latest={latest} status={live.socketStatus} />}
          {page === "analytics" && <AnalyticsPage />}
          {page === "manual" && <ManualPage onSaved={live.refresh} notify={setToast} />}
          {page === "alerts" && <AlertsPage alerts={live.alerts} />}
          {page === "sensors" && <SensorsPage sensors={live.sensors} latest={latest} />}
          {page === "settings" && <SettingsPage notify={setToast} />}
          <footer className="app-footer"><span>© 2026 AERO-HUB Monitoring</span><span>Environmental data for awareness · Not a certified AQI measurement</span></footer>
        </div>
      </main>
      {toast && <div className="toast"><CircleAlert size={17} />{toast}<button onClick={() => setToast("")}>×</button></div>}
    </div>
  );
}

function IntroPage() {
  return (
    <main className="intro-page" id="intro">
      <header className="intro-nav">
        <a className="intro-brand" href="#intro" aria-label="AERO-HUB home">
          <img src="/aero-hub-wordmark.png" alt="AERO-HUB" />
        </a>
        <a className="intro-nav-link" href="#how-it-works">About the project <ArrowDownRight size={14} /></a>
      </header>

      <section className="intro-hero">
        <div className="intro-copy">
          <div className="intro-kicker"><span className="intro-live-dot" /> AN IoT ENVIRONMENTAL MONITORING PROJECT</div>
          <h1>Understand the air.<br /><span>Shape a better tomorrow.</span></h1>
          <p className="intro-lede">
            AERO-HUB is a smart air pollution monitoring system that brings connected
            environmental sensors and real-time analytics together—so local air conditions
            are easier to observe, understand, and explore.
          </p>
          <div className="intro-actions">
            <a className="primary-button intro-explore" href="#dashboard">
              Explore the dashboard <ArrowRight size={17} />
            </a>
            <a className="intro-secondary-link" href="#how-it-works">Discover the project</a>
          </div>
          <div className="intro-footnote"><MapPin size={14} /> Location-aware readings · Live updates · Clear data provenance</div>
        </div>

        <div className="intro-visual" aria-label="Illustration of the AERO-HUB sensor-to-dashboard concept">
          <div className="visual-orbit orbit-outer" />
          <div className="visual-orbit orbit-inner" />
          <div className="visual-center">
            <span className="visual-leaf"><Leaf size={32} /></span>
            <span className="visual-center-label">AIR, IN FOCUS</span>
          </div>
          <div className="visual-node node-temp"><Thermometer size={17} /><span>BMP280</span></div>
          <div className="visual-node node-gas"><Activity size={17} /><span>GAS SENSORS</span></div>
          <div className="visual-node node-dust"><Cloud size={17} /><span>PARTICULATES</span></div>
          <div className="visual-node node-site"><MapPin size={17} /><span>LOCAL SITES</span></div>
          <div className="visual-caption"><RadioTower size={15} /><span>CONNECTED SENSING</span><i /></div>
        </div>
      </section>

      <section className="intro-principles" id="how-it-works">
        <div className="intro-section-heading">
          <span>THE PROJECT THEME</span>
          <h2>From a sensor reading to a clearer picture.</h2>
          <p>Small-scale sensing, connected data, and transparent interpretation—built around the places we live.</p>
        </div>
        <div className="principle-grid">
          <article className="principle-card">
            <span className="principle-icon mint"><RadioTower size={19} /></span>
            <span className="principle-number">01 / SENSE</span>
            <h3>Observe the environment</h3>
            <p>A Raspberry Pi gathers temperature, pressure, gas-sensor output, and calibrated particulate estimates from connected sensors.</p>
          </article>
          <article className="principle-card">
            <span className="principle-icon cyan"><Activity size={19} /></span>
            <span className="principle-number">02 / CONNECT</span>
            <h3>Make readings useful</h3>
            <p>Validated readings are stored with their time, source, and location, then shared with the dashboard as new data arrives.</p>
          </article>
          <article className="principle-card">
            <span className="principle-icon violet"><MapPin size={19} /></span>
            <span className="principle-number">03 / UNDERSTAND</span>
            <h3>Explore air by place</h3>
            <p>View sensor sites on a map, inspect nearby measurements, follow trends, and see when official comparisons need more data.</p>
          </article>
        </div>
        <div className="intro-bottom">
          <span><strong>AERO-HUB</strong> · A prototype for local environmental awareness</span>
          <a href="#dashboard">Enter monitoring dashboard <ArrowRight size={14} /></a>
        </div>
      </section>
    </main>
  );
}

function PageHeading({ eyebrow, title, description, action }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function Overview({ latest, data, alerts, sensors, lastSeen, setPage, notify }) {
  const score = latest?.air_quality_score;
  const sensorCount = sensors.filter((sensor) => sensor.status === "online").length;
  const totalSensors = Math.max(sensors.length, 4);
  const [locations, setLocations] = useState([]);
  const [selectedArea, setSelectedArea] = useState(null);
  const [selectedCenter, setSelectedCenter] = useState(null);
  const [radiusKm, setRadiusKm] = useState(5);
  const [areaLoading, setAreaLoading] = useState(false);
  const [areaError, setAreaError] = useState("");
  const areaRequestSequence = useRef(0);

  useEffect(() => {
    let active = true;
    const refreshLocations = () => api("/api/sensors/locations")
      .then((sites) => { if (active) setLocations(sites); })
      .catch((error) => { if (active) setAreaError(error.message); });
    refreshLocations();
    const timer = window.setInterval(refreshLocations, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!latest || latest.latitude == null || latest.longitude == null) return;
    const site = {
      location_name: latest.location_name || "Unnamed site",
      latitude: latest.latitude,
      longitude: latest.longitude,
      latest,
    };
    setLocations((current) => [
      site,
      ...current.filter((item) => item.location_name !== site.location_name
        || item.latitude !== site.latitude || item.longitude !== site.longitude),
    ]);
  }, [latest?.id]);

  const selectArea = async (latitude, longitude, locationName = "Selected area") => {
    const center = { latitude, longitude, location_name: locationName };
    const requestId = ++areaRequestSequence.current;
    setSelectedCenter(center);
    setAreaLoading(true);
    setAreaError("");
    try {
      const query = new URLSearchParams({
        latitude: String(latitude),
        longitude: String(longitude),
        radius_km: String(radiusKm),
      });
      const result = await api(`/api/sensors/area?${query}`);
      if (requestId === areaRequestSequence.current) setSelectedArea(result);
    } catch (error) {
      if (requestId === areaRequestSequence.current) {
        setSelectedArea(null);
        setAreaError(error.message);
        notify(error.message);
      }
    } finally {
      if (requestId === areaRequestSequence.current) setAreaLoading(false);
    }
  };

  useEffect(() => {
    if (selectedCenter) selectArea(selectedCenter.latitude, selectedCenter.longitude, selectedCenter.location_name);
  }, [radiusKm]);

  useEffect(() => {
    if (selectedCenter && latest?.id) {
      selectArea(selectedCenter.latitude, selectedCenter.longitude, selectedCenter.location_name);
    }
  }, [latest?.id]);

  return (
    <>
      <PageHeading eyebrow="MONITORING STATION · STATION 01" title="Good afternoon" description="Here’s the latest snapshot of your local air environment." action={<button className="secondary-button" onClick={() => setPage("live")}><Radio size={16} /> View live data</button>} />
      {latest?.source === "simulation" && <div className="demo-banner"><span className="demo-spark" /> Demo data is active — readings are simulated, not from connected hardware.</div>}
      <section className="overview-top">
        <article className={`quality-card panel quality-${scoreColor(score ?? 0)}`}>
          <div className="quality-copy">
            <div className="card-kicker"><span className="quality-pulse" /> PROJECT AIR-QUALITY SCORE</div>
            <div className="quality-number">{score ?? "—"}<span>/ 100</span></div>
            <div className="quality-status">{latest?.pollution_status ?? "Awaiting readings"}</div>
            <p>A project indicator based on available gas and dust sensor readings. Not a regulatory AQI.</p>
            <div className="quality-updated"><Clock3 size={14} /> Updated {latest ? stamp(latest.timestamp) : "when sensor data arrives"}</div>
          </div>
          <div className="score-gauge" style={{ "--score": `${score ?? 0}%` }}><div><Wind size={26} /><span>LIVE</span></div></div>
        </article>
        <article className="station-summary panel">
          <div className="summary-title">Station health <span className="summary-icon"><Activity size={17} /></span></div>
          <div className="health-number">{sensorCount}<span> / {totalSensors}</span></div>
          <div className="health-label">sensors reporting</div>
          <div className="health-bar"><span style={{ width: `${sensorCount / totalSensors * 100}%` }} /></div>
          <div className="health-bottom"><span><i className="status-pip green-pip" /> {sensorCount ? "Hardware active" : "Waiting for data"}</span><button onClick={() => setPage("sensors")}>Details <ChevronDown size={14} /></button></div>
          <div className="last-communication"><span>LAST COMMUNICATION</span><strong>{lastSeen}</strong></div>
        </article>
      </section>
      <section className="map-section">
        <div className="section-title-row map-title-row">
          <div><h2>Explore air quality by location</h2><p>Select a sensor marker or click the map to inspect readings in that area.</p></div>
          <label className="radius-control">Search radius
            <select value={radiusKm} onChange={(event) => setRadiusKm(Number(event.target.value))}>
              {[1, 5, 10, 25].map((radius) => <option key={radius} value={radius}>{radius} km</option>)}
            </select>
          </label>
        </div>
        <div className="map-layout panel">
          <div className="map-column">
            <LocationMap locations={locations} onSelect={selectArea} selectedCenter={selectedCenter} />
            <div className="map-legend"><span><i className="map-dot hardware" /> Sensor location</span><span><i className="map-dot demo" /> Simulated location</span><span>{locations.length} mapped location{locations.length === 1 ? "" : "s"}</span></div>
          </div>
          <AreaDetails area={selectedArea} center={selectedCenter} radiusKm={radiusKm} loading={areaLoading} error={areaError} />
        </div>
      </section>
      <div className="section-title-row"><div><h2>Sensor readings</h2><p>Current measurements from your environment</p></div><span className="updated-note"><RefreshCw size={13} /> Updates in real time</span></div>
      <section className="metric-grid">
        <MetricCard title="Temperature" value={fmt(latest?.temperature)} unit="°C" icon={Thermometer} tone="green" data={data} dataKey="temperature" note="BMP280 · ambient" />
        <MetricCard title="Atmospheric pressure" value={fmt(latest?.pressure, 0)} unit="hPa" icon={Gauge} tone="blue" data={data} dataKey="pressure" note="BMP280 · barometric" />
        <MetricCard title="Carbon monoxide" value={fmt(latest?.co_ppm, 2)} unit="ppm" icon={Cloud} tone="purple" data={data} dataKey="co_ppm" note="MQ-7 · calibrated reading" />
        <MetricCard title="Dust concentration" value={fmt(latest?.dust_ug_m3, 1)} unit="µg/m³" icon={Droplets} tone="amber" data={data} dataKey="dust_ug_m3" note="Sharp · estimate requires calibration" />
      </section>
      <section className="dashboard-lower">
        <article className="panel trend-panel">
          <div className="panel-heading"><div><h2>Pollution trends</h2><p>Recent measurements across sensors</p></div><button className="text-button" onClick={() => setPage("analytics")}>View analytics <ArrowUpRight size={14} /></button></div>
          <TrendChart data={data} compact />
        </article>
        <article className="panel activity-panel">
          <div className="panel-heading"><div><h2>Recent activity</h2><p>Latest sensor events and alerts</p></div><button className="dots">···</button></div>
          <ActivityList alerts={alerts.slice(0, 4)} />
        </article>
      </section>
    </>
  );
}

function AreaDetails({ area, center, radiusKm, loading, error }) {
  if (!center) {
    return <aside className="area-details empty-area"><span className="area-pin"><Radio size={19} /></span><strong>Choose a location</strong><p>Click a map marker or any point on the map. Nearby saved sensor readings will appear here.</p><span className="area-search-radius">Search radius: {radiusKm} km</span></aside>;
  }
  const latest = area?.latest;
  const warnings = area?.warnings || [];
  return (
    <aside className="area-details">
      <div className="area-heading"><div><div className="eyebrow">SELECTED AREA</div><h3>{center.location_name || "Map selection"}</h3><span>{center.latitude.toFixed(4)}, {center.longitude.toFixed(4)} · {area?.center.radius_km || 5} km</span></div><span className="area-pin"><Radio size={17} /></span></div>
      {loading && <div className="area-loading"><span className="loading-spinner" /> Loading nearby measurements…</div>}
      {error && <div className="area-error"><CircleAlert size={14} />{error}</div>}
      {!loading && !latest && <div className="area-no-data"><Radio size={16} /><span>No sensor readings found within this radius in the last 24 hours. Select a marked station or add location coordinates to incoming data.</span></div>}
      {latest && <>
        <div className="area-updated"><Clock3 size={12} /> Updated {stamp(latest.timestamp)} · {area.sample_count_24h} samples / 24h</div>
        <div className="area-metrics">
          <div><span>TEMPERATURE</span><strong>{fmt(latest.temperature)}{latest.temperature == null ? "" : " °C"}</strong></div>
          <div><span>PRESSURE</span><strong>{fmt(latest.pressure, 0)}{latest.pressure == null ? "" : " hPa"}</strong></div>
          <div><span>CO</span><strong>{fmt(latest.co_ppm, 2)}{latest.co_ppm == null ? "" : " ppm"}</strong></div>
          <div><span>PARTICULATE</span><strong>{fmt(latest.dust_ug_m3)}{latest.dust_ug_m3 == null ? "" : " µg/m³"}</strong></div>
        </div>
        <div className="warning-list">
          <div className="warning-heading"><strong>Health & air-quality guidance</strong><span>24-hour averages</span></div>
          {warnings.map((warning) => <GuidelineWarning key={`${warning.authority}:${warning.pollutant}`} warning={warning} />)}
        </div>
        <div className="coverage-note">Data window: {area.coverage_hours} / 24 hours. A warning needs a calibrated particle type and at least one reading in every hour of that 24-hour window.</div>
        <div className="authority-links">
          <a href="https://www.who.int/publications/i/item/9789240034228" target="_blank" rel="noreferrer">WHO Air Quality Guidelines ↗</a>
          <a href="https://cpcb.nic.in/uploads/Projects/AQI/AQI_Faq.pdf" target="_blank" rel="noreferrer">CPCB AQI FAQ ↗</a>
          <a href="https://wmo.int/activities/global-atmosphere-watch-programme-gaw" target="_blank" rel="noreferrer">WMO Global Atmosphere Watch ↗</a>
        </div>
      </>}
    </aside>
  );
}

function GuidelineWarning({ warning }) {
  const tone = warning.status === "exceeds" || ["poor", "very_poor", "severe"].includes(warning.sub_index?.severity)
    ? "critical"
    : warning.status === "within" || ["good", "satisfactory"].includes(warning.sub_index?.severity)
      ? "good"
      : warning.sub_index?.severity === "moderate"
        ? "warning"
      : warning.status === "forecast_unavailable"
        ? "info"
        : "pending";
  return (
    <div className={`guideline-warning ${tone}`}>
      <span className="warning-sign"><CircleAlert size={14} /></span>
      <div className="guideline-copy"><strong>{warning.authority} · {warning.pollutant}</strong><span>{warning.label}</span></div>
      <div className="guideline-value">{warning.sub_index ? `${warning.sub_index.value} · ${warning.sub_index.category}` : warning.value == null ? "—" : `${warning.value} ${warning.unit}`}</div>
    </div>
  );
}

function LivePage({ data, latest, status }) {
  const [windowKey, setWindowKey] = useState("5m");
  const [windowRows, setWindowRows] = useState(data);
  const windows = { "60s": 60_000, "5m": 300_000, "1h": 3_600_000, "24h": 86_400_000 };
  useEffect(() => {
    let active = true;
    const start = new Date(Date.now() - windows[windowKey]).toISOString();
    api(`/api/sensors/history?start=${encodeURIComponent(start)}&limit=50000`)
      .then((rows) => { if (active) setWindowRows(rows); })
      .catch(() => { if (active) setWindowRows([]); });
    return () => { active = false; };
  }, [windowKey]);
  const combined = new Map([...windowRows, ...data].map((row) => [row.id ?? row.timestamp, row]));
  const filtered = [...combined.values()]
    .filter((row) => Date.now() - new Date(row.timestamp).getTime() <= windows[windowKey])
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  return <>
    <PageHeading eyebrow="REAL-TIME STREAM" title="Live monitoring" description="Streaming sensor measurements, delivered over WebSocket." action={<span className={`connection-pill ${status}`}><span className="status-pip" />{status === "connected" ? "WebSocket connected" : status}</span>} />
    <div className="panel live-chart-panel">
      <div className="panel-heading"><div><h2>Live sensor streams</h2><p>Latest update: {stamp(latest?.timestamp)}</p></div><div className="segmented">{Object.keys(windows).map((range) => <button key={range} className={windowKey === range ? "selected" : ""} onClick={() => setWindowKey(range)}>{range}</button>)}</div></div>
      <TrendChart data={filtered} />
    </div>
    <div className="metric-grid live-metrics">
      <MetricCard title="Temperature" value={fmt(latest?.temperature)} unit="°C" icon={Thermometer} tone="green" data={filtered} dataKey="temperature" note="Live value" />
      <MetricCard title="Carbon monoxide" value={fmt(latest?.co_ppm, 2)} unit="ppm" icon={Cloud} tone="blue" data={filtered} dataKey="co_ppm" note="MQ-7" />
      <MetricCard title="MQ-135 gas sensor" value={fmt(latest?.mq135_raw, 3)} unit="V" icon={Activity} tone="purple" data={filtered} dataKey="mq135_raw" note="Raw voltage · not calibrated" />
      <MetricCard title="Dust estimate" value={fmt(latest?.dust_ug_m3)} unit="µg/m³" icon={Droplets} tone="amber" data={filtered} dataKey="dust_ug_m3" note="Use calibrated conversion" />
    </div>
  </>;
}

function AnalyticsPage() {
  const [range, setRange] = useState("24h");
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState({});
  const [previousStats, setPreviousStats] = useState({});
  const [comparePrevious, setComparePrevious] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [dates, setDates] = useState({ start: "", end: "" });
  const load = async (custom = dates) => {
    setLoading(true);
    setError("");
    try {
      const end = custom.end ? new Date(custom.end) : new Date();
      const start = custom.start ? new Date(custom.start) : new Date(end.getTime() - ({ "1h": 3600000, "24h": 86400000, "7d": 604800000 }[range]));
      const query = `?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}&limit=50000`;
      const duration = end.getTime() - start.getTime();
      const previousStart = new Date(start.getTime() - duration);
      const previousQuery = `?start=${encodeURIComponent(previousStart.toISOString())}&end=${encodeURIComponent(start.toISOString())}`;
      const [readings, statistics, previous] = await Promise.all([
        api(`/api/sensors/history${query}`),
        api(`/api/sensors/statistics${query}`),
        comparePrevious ? api(`/api/sensors/statistics${previousQuery}`) : Promise.resolve({}),
      ]);
      setRows(readings);
      setStats(statistics);
      setPreviousStats(previous);
    } catch (reason) { setError(reason.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load();   }, [range, comparePrevious]); // eslint-disable-line react-hooks/exhaustive-deps
  const exportCsv = () => {
    if (!rows.length) return setError("There are no readings in this range to export.");
    const columns = ["timestamp", "temperature", "pressure", "altitude", "co_ppm", "mq135_raw", "mq135_estimated_ppm", "dust_voltage", "dust_ug_m3", "source"];
    const exportColumns = [...columns, "dust_particle_size", "location_name", "latitude", "longitude"];
    const csv = [exportColumns.join(","), ...rows.map((row) => exportColumns.map((column) => JSON.stringify(row[column] ?? "")).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = `airsense-readings-${new Date().toISOString().slice(0, 10)}.csv`; link.click();
    URL.revokeObjectURL(url);
  };
  return <>
    <PageHeading eyebrow="DATA EXPLORER" title="Historical analytics" description="Explore stored sensor readings, compare trends, and export your data." action={<button className="primary-button" onClick={exportCsv}><ArrowDownRight size={16} /> Export CSV</button>} />
    <div className="panel filter-panel">
      <div className="segmented">{["1h", "24h", "7d"].map((item) => <button key={item} className={range === item ? "selected" : ""} onClick={() => { setRange(item); setDates({ start: "", end: "" }); }}>{item}</button>)}</div>
      <label>From <input type="datetime-local" value={dates.start} onChange={(event) => setDates({ ...dates, start: event.target.value })} /></label>
      <label>To <input type="datetime-local" value={dates.end} onChange={(event) => setDates({ ...dates, end: event.target.value })} /></label>
      <label className="compare-control"><input type="checkbox" checked={comparePrevious} onChange={(event) => setComparePrevious(event.target.checked)} /> Compare previous period</label>
      <button className="secondary-button" onClick={() => load()}>Apply filters</button>
    </div>
    {error && <div className="inline-error">{error}</div>}
    <div className="stats-grid">{Object.entries({ temperature: "Temperature", co_ppm: "Carbon monoxide", mq135_raw: "MQ-135 voltage", dust_ug_m3: "Dust estimate" }).map(([key, label]) => <StatCard key={key} label={label} data={stats[key]} previous={previousStats[key]} comparing={comparePrevious} unit={key === "temperature" ? "°C" : key === "co_ppm" ? "ppm" : key === "mq135_raw" ? "V" : "µg/m³"} />)}</div>
    <article className="panel analytics-chart"><div className="panel-heading"><div><h2>Sensor history</h2><p>{loading ? "Loading stored readings…" : `${rows.length} readings in selected period`}</p></div><span className="source-key"><i className="source-dot" /> All sources</span></div><TrendChart data={rows} /></article>
    <article className="panel table-panel"><div className="panel-heading"><div><h2>Recent readings</h2><p>Most recent records in the selected range</p></div></div><ReadingsTable rows={[...rows].reverse().slice(0, 8)} /></article>
  </>;
}

function StatCard({ label, data, previous, comparing, unit }) {
  const delta = data?.average != null && previous?.average != null
    ? Number(previous.average) === 0
      ? null
      : ((Number(data.average) - Number(previous.average)) / Math.abs(Number(previous.average))) * 100
    : null;
  return <article className="panel stat-card"><span>{label}</span><strong>{data?.average == null ? "—" : `${Number(data.average).toFixed(1)}${unit}`}</strong><div><span>MIN <b>{data?.min == null ? "—" : Number(data.min).toFixed(1)}</b></span><span>MAX <b>{data?.max == null ? "—" : Number(data.max).toFixed(1)}</b></span></div>{comparing && <small className={`comparison-delta ${delta > 0 ? "up" : "down"}`}>{delta == null ? "No previous-period baseline" : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}% vs previous period`}</small>}</article>;
}

function ReadingsTable({ rows }) {
  if (!rows.length) return <div className="empty-table">No records in this time range.</div>;
  return <div className="table-scroll"><table><thead><tr><th>TIME</th><th>TEMP</th><th>PRESSURE</th><th>CO</th><th>MQ-135</th><th>DUST</th><th>SOURCE</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{stamp(row.timestamp)}</td><td>{fmt(row.temperature)} °C</td><td>{fmt(row.pressure, 0)} hPa</td><td>{fmt(row.co_ppm, 2)} ppm</td><td>{fmt(row.mq135_raw, 3)} V</td><td>{fmt(row.dust_ug_m3)} µg/m³</td><td><SourceBadge source={row.source} /></td></tr>)}</tbody></table></div>;
}

function ManualPage({ onSaved, notify }) {
  const initial = { temperature: "", pressure: "", co_ppm: "", mq135_raw: "", dust_ug_m3: "", dust_particle_size: "unknown", location_name: "", latitude: "", longitude: "", timestamp: "" };
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const submit = async (event) => {
    event.preventDefault(); setError("");
    const body = Object.fromEntries(Object.entries(form)
      .filter(([, value]) => value !== "")
      .map(([key, value]) => [key, key === "timestamp"
        ? new Date(value).toISOString()
        : ["location_name", "dust_particle_size"].includes(key)
          ? value
          : Number(value)]));
    if (!Object.keys(body).some((key) => key !== "timestamp")) return setError("Enter at least one sensor measurement.");
    setBusy(true);
    try {
      await api("/api/sensors/manual", { method: "POST", body: JSON.stringify(body) });
      setForm(initial); onSaved(); notify("Manual sensor reading saved.");
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  return <>
    <PageHeading eyebrow="DATA INPUT" title="Manual data entry" description="Add a measurement when testing sensors or recording a field reading." />
    <div className="manual-layout"><form className="panel form-panel" onSubmit={submit}>
      <div className="panel-heading"><div><h2>New sensor reading</h2><p>Manual records are labeled separately from device and demo data.</p></div><span className="manual-badge">MANUAL</span></div>
      <div className="form-grid">
        <Field label="Temperature" unit="°C" value={form.temperature} onChange={(value) => change("temperature", value)} min="-80" max="100" />
        <Field label="Atmospheric pressure" unit="hPa" value={form.pressure} onChange={(value) => change("pressure", value)} min="100" max="1200" />
        <Field label="Carbon monoxide (CO)" unit="ppm" value={form.co_ppm} onChange={(value) => change("co_ppm", value)} min="0" max="10000" />
        <Field label="MQ-135 raw output" unit="V" value={form.mq135_raw} onChange={(value) => change("mq135_raw", value)} min="0" max="5" step="0.001" />
        <Field label="Dust estimate" unit="µg/m³" value={form.dust_ug_m3} onChange={(value) => change("dust_ug_m3", value)} min="0" max="100000" />
        <label className="field"><span>Particulate type (calibrated only)</span><select value={form.dust_particle_size} onChange={(event) => change("dust_particle_size", event.target.value)}><option value="unknown">Unknown / uncalibrated</option><option value="pm2_5">PM2.5</option><option value="pm10">PM10</option></select></label>
        <Field label="Site / area name" unit="name" type="text" value={form.location_name} onChange={(value) => change("location_name", value)} maxLength="120" />
        <Field label="Latitude" unit="°" value={form.latitude} onChange={(value) => change("latitude", value)} min="-90" max="90" step="any" />
        <Field label="Longitude" unit="°" value={form.longitude} onChange={(value) => change("longitude", value)} min="-180" max="180" step="any" />
        <label className="field"><span>Reading timestamp</span><input type="datetime-local" value={form.timestamp} onChange={(event) => change("timestamp", event.target.value)} /><small>Leave blank to use the current time</small></label>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <div className="form-footer"><span><CircleAlert size={14} /> Only enter calibrated concentration values when available.</span><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : <><Check size={16} /> Save reading</>}</button></div>
    </form>
    <aside className="panel info-panel"><div className="info-icon"><Cloud size={20} /></div><h3>Data source clarity</h3><p>Manual measurements are stored with <code>source: manual</code>. They appear in dashboard charts and are distinct from Raspberry Pi and simulation records.</p><div className="source-examples"><span><i className="source-dot hardware" /> Raspberry Pi</span><span><i className="source-dot manual-dot" /> Manual</span><span><i className="source-dot demo-dot" /> Simulation</span></div></aside></div>
  </>;
}

function Field({ label, unit, value, onChange, type = "number", ...inputProps }) {
  return <label className="field"><span>{label}</span><div className="input-with-unit"><input type={type} value={value} onChange={(event) => onChange(event.target.value)} {...inputProps} /><i>{unit}</i></div></label>;
}

function AlertsPage({ alerts }) {
  return <>
    <PageHeading eyebrow="THRESHOLD WATCH" title="Pollution alerts" description="Threshold warnings generated automatically when sensor readings exceed configured limits." />
    <div className="alert-summary-grid"><div className="panel alert-summary"><span className="alert-summary-icon warning"><CircleAlert size={18} /></span><div><strong>{alerts.filter((alert) => alert.severity === "warning").length}</strong><span>Warnings shown</span></div></div><div className="panel alert-summary"><span className="alert-summary-icon critical"><CircleAlert size={18} /></span><div><strong>{alerts.filter((alert) => alert.severity === "critical").length}</strong><span>Critical alerts shown</span></div></div><div className="panel alert-summary"><span className="alert-summary-icon healthy"><Check size={18} /></span><div><strong>{alerts.length ? "Monitoring" : "Clear"}</strong><span>Threshold status</span></div></div></div>
    <section className="panel alert-list-panel"><div className="panel-heading"><div><h2>Alert history</h2><p>Most recent sensor threshold events</p></div><span className="count-pill">{alerts.length} recent</span></div><ActivityList alerts={alerts} expanded /></section>
    <div className="disclaimer"><CircleAlert size={16} /><p>Thresholds are project defaults for demonstration, not health guidance or regulatory limits. Configure according to sensor calibration and applicable standards.</p></div>
  </>;
}

function ActivityList({ alerts, expanded = false }) {
  if (!alerts.length) return <div className="empty-activity"><span className="check-circle"><Check size={16} /></span><div><strong>No recent alerts</strong><span>Alerts will be listed here when configured thresholds are exceeded.</span></div></div>;
  return <div className={`activity-list ${expanded ? "expanded" : ""}`}>{alerts.map((alert) => <div className="activity-item" key={alert.id}><span className={`activity-marker ${alert.severity}`}><CircleAlert size={15} /></span><div className="activity-copy"><strong>{alert.alert_type} · {alert.severity}</strong><span>{alert.message}</span><small>{stamp(alert.timestamp)} · {fmt(alert.sensor_value, 2)}</small></div><span className={`severity-badge ${alert.severity}`}>{alert.severity}</span></div>)}</div>;
}

function SensorsPage({ sensors, latest }) {
  const definitions = [
    { name: "BMP280", type: "Temperature · Pressure", values: `${fmt(latest?.temperature)} °C / ${fmt(latest?.pressure, 0)} hPa`, icon: Thermometer },
    { name: "MQ-7", type: "Carbon monoxide", values: latest?.co_ppm == null ? "No reading" : `${fmt(latest.co_ppm, 2)} ppm`, icon: Cloud },
    { name: "MQ-135", type: "Broad-spectrum gas sensor", values: latest?.mq135_raw == null ? "No reading" : `${fmt(latest.mq135_raw, 3)} V`, icon: Activity },
    { name: "Sharp GP2Y101AU0F", type: "Optical dust sensor", values: latest?.dust_ug_m3 == null ? "No reading" : `${fmt(latest.dust_ug_m3)} µg/m³`, icon: Droplets },
  ];
  return <>
    <PageHeading eyebrow="DEVICE FLEET" title="Sensor management" description="Monitor sensor communications, latest readings, and calibration state." />
    <div className="sensor-list">{definitions.map((sensor) => {
      const state = sensors.find((item) => item.sensor_name === sensor.name || (sensor.name.startsWith("Sharp") && item.sensor_name === "Sharp dust"));
      return <article className="panel sensor-row" key={sensor.name}><span className="sensor-symbol"><sensor.icon size={20} /></span><div className="sensor-identity"><strong>{sensor.name}</strong><span>{sensor.type}</span></div><div className="sensor-reading"><span>LATEST READING</span><strong>{sensor.values}</strong></div><div className="sensor-calibration"><span>CALIBRATION</span><strong>{state?.calibration_status || "Not calibrated"}</strong></div><div className={`sensor-state ${state?.status === "online" ? "online" : ""}`}><i />{state?.status || "offline"}</div></article>;
    })}</div>
    <div className="disclaimer"><CircleAlert size={16} /><p>MQ sensors require warm-up, clean-air baseline measurements, and a load-resistor-specific calibration curve. Dust concentration is an estimate and must be validated against a reference instrument.</p></div>
  </>;
}

function SettingsPage({ notify }) {
  const [thresholds, setThresholds] = useState({});
  const [demo, setDemo] = useState(false);
  const [demoLocation, setDemoLocation] = useState({ location_name: "", latitude: "", longitude: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([api("/api/thresholds"), api("/api/settings/demo"), api("/api/settings/demo-location")])
      .then(([values, demoState, location]) => {
        setThresholds(values);
        setDemo(demoState.enabled);
        setDemoLocation({
          location_name: location.location_name || "",
          latitude: location.latitude ?? "",
          longitude: location.longitude ?? "",
        });
      })
      .catch((reason) => setError(reason.message));
  }, []);
  const updateValue = (sensor, key, value) => setThresholds((current) => ({ ...current, [sensor]: { ...current[sensor], [key]: value } }));
  const saveThreshold = async (sensor) => {
    setBusy(true); setError("");
    try {
      const body = thresholds[sensor];
      await api(`/api/thresholds/${sensor}`, { method: "PUT", body: JSON.stringify({ warning_threshold: Number(body.warning_threshold), critical_threshold: Number(body.critical_threshold) }) });
      notify(`${sensor.toUpperCase()} thresholds updated.`);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  const toggleDemo = async () => {
    const enabled = !demo;
    setBusy(true); setError("");
    try { await api("/api/settings/demo", { method: "PUT", body: JSON.stringify({ enabled }) }); setDemo(enabled); notify(enabled ? "Demo mode enabled." : "Demo mode disabled."); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  const saveDemoLocation = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    const body = {
      location_name: demoLocation.location_name || null,
      latitude: demoLocation.latitude === "" ? null : Number(demoLocation.latitude),
      longitude: demoLocation.longitude === "" ? null : Number(demoLocation.longitude),
    };
    try {
      await api("/api/settings/demo-location", { method: "PUT", body: JSON.stringify(body) });
      notify("Demo station location saved. New demo readings will include it.");
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setError("Geolocation is not available in this browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => setDemoLocation((current) => ({
        location_name: current.location_name || "My location",
        latitude: coords.latitude.toFixed(5),
        longitude: coords.longitude.toFixed(5),
      })),
      (reason) => setError(`Could not read your location: ${reason.message}`),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  };
  return <>
    <PageHeading eyebrow="CONFIGURATION" title="System settings" description="Manage project thresholds and development data behavior." />
    {error && <div className="inline-error">{error}</div>}
    <div className="settings-layout">
      <section className="panel settings-panel"><div className="panel-heading"><div><h2>Pollution thresholds</h2><p>Generate warnings and critical alerts at these values.</p></div></div>
        <div className="threshold-table"><div className="threshold-header"><span>SENSOR</span><span>WARNING</span><span>CRITICAL</span><span /></div>
          {[["co", "Carbon monoxide", "ppm"], ["mq135", "MQ-135 raw voltage", "V"], ["dust", "Dust estimate", "µg/m³"]].map(([key, label, unit]) => <div className="threshold-row" key={key}><div><strong>{label}</strong><span>{unit}</span></div><input aria-label={`${label} warning threshold`} type="number" step="0.1" value={thresholds[key]?.warning_threshold ?? ""} onChange={(event) => updateValue(key, "warning_threshold", event.target.value)} /><input aria-label={`${label} critical threshold`} type="number" step="0.1" value={thresholds[key]?.critical_threshold ?? ""} onChange={(event) => updateValue(key, "critical_threshold", event.target.value)} /><button className="save-small" disabled={busy || !thresholds[key]} onClick={() => saveThreshold(key)}>Save</button></div>)}
        </div>
        <p className="setting-note"><CircleAlert size={14} /> Thresholds are illustrative defaults. Verify units and calibrate before relying on alerts.</p>
      </section>
      <section className="panel settings-panel demo-settings"><div className="panel-heading"><div><h2>Demo mode</h2><p>Simulate readings for UI development and demonstrations.</p></div><span className={`demo-state ${demo ? "enabled" : ""}`}>{demo ? "ON" : "OFF"}</span></div><div className="demo-setting-body"><div className="demo-orbit"><Activity size={22} /></div><div><strong>{demo ? "Simulation is running" : "Using hardware readings"}</strong><p>{demo ? "A synthetic sample is generated every five seconds and clearly labeled as DEMO DATA." : "Enable demo mode to generate sample readings when no device is connected."}</p></div></div><button className={`secondary-button ${demo ? "disable-demo" : ""}`} onClick={toggleDemo} disabled={busy}>{demo ? "Disable demo mode" : "Enable demo mode"}</button></section>
    </div>
    <form className="panel settings-panel demo-location-settings" onSubmit={saveDemoLocation}>
      <div className="panel-heading"><div><h2>Demo station location</h2><p>Optional coordinates used only for generated demo readings.</p></div></div>
      <div className="location-form-grid">
        <label className="field"><span>Site name</span><input value={demoLocation.location_name} maxLength="120" onChange={(event) => setDemoLocation({ ...demoLocation, location_name: event.target.value })} placeholder="e.g. North campus" /></label>
        <label className="field"><span>Latitude</span><input type="number" step="any" min="-90" max="90" value={demoLocation.latitude} onChange={(event) => setDemoLocation({ ...demoLocation, latitude: event.target.value })} placeholder="e.g. 28.6139" /></label>
        <label className="field"><span>Longitude</span><input type="number" step="any" min="-180" max="180" value={demoLocation.longitude} onChange={(event) => setDemoLocation({ ...demoLocation, longitude: event.target.value })} placeholder="e.g. 77.2090" /></label>
        <div className="location-actions"><button type="button" className="secondary-button" onClick={useMyLocation} disabled={busy}>Use my location</button><button className="primary-button" disabled={busy}>Save demo location</button></div>
      </div>
      <p className="setting-note"><CircleAlert size={14} /> Browser location is requested only after you click the button. Coordinates are saved only if you choose Save.</p>
    </form>
    <section className="panel settings-panel connection-settings"><div className="panel-heading"><div><h2>API connection</h2><p>Frontend data services use the VITE_API_URL environment variable.</p></div></div><div className="connection-detail"><span>REST API</span><code>{import.meta.env.VITE_API_URL || "http://localhost:8000"}</code><span>WebSocket</span><code>/ws/readings</code></div></section>
  </>;
}

function SourceBadge({ source }) {
  return <span className={`source-badge ${source || "raspberry_pi"}`}><i />{source === "simulation" ? "Demo" : source === "manual" ? "Manual" : "Raspberry Pi"}</span>;
}
