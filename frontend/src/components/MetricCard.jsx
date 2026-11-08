import { SingleTrend } from "./Charts";

export function MetricCard({ title, value, unit, icon: Icon, tone, data, dataKey, note }) {
  return (
    <article className="metric-card panel">
      <div className="metric-head">
        <div className={`metric-icon ${tone}`}><Icon size={18} strokeWidth={1.8} /></div>
        <span className="metric-name">{title}</span>
        <button className="more-button" aria-label={`${title} details`}>···</button>
      </div>
      <div className="metric-value">{value ?? "—"}<span>{value == null ? "" : unit}</span></div>
      <div className="metric-meta">{note}</div>
      <SingleTrend data={data} dataKey={dataKey} color={tone === "green" ? "#59d9ae" : tone === "blue" ? "#58b8ff" : tone === "purple" ? "#b69aff" : "#f6bd60"} unit={unit} />
    </article>
  );
}
