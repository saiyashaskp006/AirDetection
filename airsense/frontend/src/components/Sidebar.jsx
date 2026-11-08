import {
  Activity, Bell, ChartNoAxesCombined, Cloud, Gauge, RadioTower, Settings2, X,
} from "lucide-react";

const items = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "live", label: "Live monitoring", icon: Activity },
  { id: "analytics", label: "Analytics", icon: ChartNoAxesCombined },
  { id: "manual", label: "Manual entry", icon: Cloud },
  { id: "alerts", label: "Pollution alerts", icon: Bell },
  { id: "sensors", label: "Sensors", icon: RadioTower },
  { id: "settings", label: "Settings", icon: Settings2 },
];

export function Sidebar({ page, setPage, open, onClose }) {
  return (
    <>
      {open && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={onClose} />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand">
          <a className="brand-link" href="#intro" aria-label="Return to AERO-HUB introduction">
            <img src="/aero-hub-wordmark.png" alt="AERO-HUB" />
          </a>
          <button className="icon-button mobile-close" onClick={onClose} aria-label="Close menu"><X size={18} /></button>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav-list" aria-label="Main navigation">
          {items.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${page === id ? "active" : ""}`} onClick={() => { setPage(id); onClose(); }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
              {id === "alerts" && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="station-card">
            <div className="station-mark"><RadioTower size={16} /></div>
            <div><span>MONITORING STATION</span><strong>Station 01 · Local</strong></div>
            <span className="online-indicator" />
          </div>
          <div className="sidebar-footer"><span className="footer-dot" /> SYSTEM OPERATIONAL <span>v1.0</span></div>
        </div>
      </aside>
    </>
  );
}
