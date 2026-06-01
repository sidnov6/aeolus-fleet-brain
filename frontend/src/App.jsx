import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { useTheme } from "./theme.js";
import Counter from "./components/Counter.jsx";
import WindFarm from "./components/WindFarm.jsx";
import ApprovalQueue from "./components/ApprovalQueue.jsx";
import IncidentDrawer from "./components/IncidentDrawer.jsx";
import AuditViewer from "./components/AuditViewer.jsx";

export default function App() {
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState(null);
  const [fleet, setFleet] = useState(null);
  const [approvals, setApprovals] = useState(null);
  const [audit, setAudit] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [err, setErr] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [f, a, au] = await Promise.all([api.fleet(), api.approvals(), api.audit()]);
      setFleet(f); setApprovals(a); setAudit(au); setErr(null);
    } catch (e) { setErr(String(e.message || e)); }
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const openDossier = async (tid) => {
    try { setDrawer(await api.incident(tid)); } catch (e) { /* healthy turbine */ }
  };
  const decide = async (id, approve) => {
    let note = "";
    if (!approve) note = window.prompt("Reason for rejection (feeds back as a training signal):", "") || "";
    try { await api.decide(id, approve, note); await refresh(); }
    catch (e) { alert(e.message); }
  };
  const toggleKill = async () => {
    const active = !fleet?.kill_switch;
    if (active && !window.confirm("Engage fleet-wide kill switch? All agent action halts.")) return;
    await api.killSwitch(active); await refresh();
  };

  const turbines = fleet?.turbines || [];
  const totalMW = turbines.reduce((s, t) => s + (t.expected_power_kw || 0), 0) / 1000;
  const meanWind = turbines.length ? turbines.reduce((s, t) => s + (t.wind_ms || 0), 0) / turbines.length : 0;
  const healthy = turbines.filter((t) => t.status === "healthy").length;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <h1>AEOLUS</h1>
          <span className="sub">AUTONOMOUS OPERATIONS BRAIN · RENEWABLE FLEET</span>
        </div>
        <div className="spacer" />
        {health && (
          <span className={`badge ${health.llm_mode === "llm" ? "live" : "fallback"}`}>
            LLM: {health.llm_mode === "llm" ? health.llm_model : "deterministic fallback"}
          </span>
        )}
        <span className="badge">site · {fleet?.site || "…"}</span>
        <button className="icon-btn" title="Toggle theme" onClick={toggle}>
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button className={`kill ${fleet?.kill_switch ? "engaged" : ""}`} onClick={toggleKill}>
          {fleet?.kill_switch ? "● KILL SWITCH ENGAGED" : "◌ Kill switch"}
        </button>
      </div>

      {err && <div style={{ padding: "10px 26px", color: "var(--critical)" }}>
        API unreachable ({err}). Start the backend: <code>uvicorn aeolus.api.main:app --port 8000</code>
      </div>}

      {/* HERO — the living wind farm */}
      <div className="hero">
        <WindFarm turbines={turbines} onSelect={(t) => openDossier(t.turbine_id)} />
        <Counter fleet={fleet} />
        <div className="scene-hud">
          <div><div className="h">FLEET OUTPUT</div><div className="v">{totalMW.toFixed(1)} MW</div></div>
          <div><div className="h">MEAN WIND</div><div className="v">{meanWind.toFixed(1)} m/s</div></div>
          <div><div className="h">HEALTHY</div><div className="v">{healthy}/{turbines.length}</div></div>
        </div>
      </div>

      <div className="layout">
        <div className="col">
          <ApprovalQueue approvals={approvals} onDecide={decide} onOpen={openDossier} />
        </div>
        <div className="col">
          <AuditViewer audit={audit} />
        </div>
      </div>

      <div className="synthetic-note">
        Real data: Kelmarsh wind farm SCADA (Zenodo, CC-BY-4.0) · German DE-LU day-ahead prices
        (energy-charts.info) · Open-Meteo hub-height wind. Synthetic & labelled: crew roster, parts
        inventory, grid commitments, and the injected degradation scenario. Click any turbine for its dossier.
      </div>

      {drawer && <IncidentDrawer data={drawer} onClose={() => setDrawer(null)} />}
    </div>
  );
}
