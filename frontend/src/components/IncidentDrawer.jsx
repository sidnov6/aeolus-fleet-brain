import React, { useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area,
  XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from "recharts";
import { eur, fmtTime } from "../util.js";

const TABS = ["Diagnosis", "Economics", "Prognosis", "Work order", "Agent trace"];

function CostCurve({ curve, chosen, naive }) {
  const data = curve
    .filter((c) => c.feasible || true)
    .map((c) => ({
      t: new Date(c.start).getTime(),
      total: c.total_cost_eur,
      lost: c.lost_revenue_eur,
      risk: c.risk_cost_eur,
      feasible: c.feasible,
    }));
  const chosenT = chosen ? new Date(chosen).getTime() : null;
  const naiveT = naive ? new Date(naive).getTime() : null;
  const fmt = (t) => new Date(t).toLocaleString("en-GB",
    { weekday: "short", hour: "2-digit", timeZone: "UTC" });
  return (
    <ResponsiveContainer width="99%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
        <CartesianGrid stroke="#1a2230" />
        <XAxis dataKey="t" tickFormatter={fmt} stroke="#8696a7" fontSize={10} />
        <YAxis stroke="#8696a7" fontSize={10} tickFormatter={(v) => "€" + (v / 1000).toFixed(0) + "k"} />
        <Tooltip
          contentStyle={{ background: "#0e141e", border: "1px solid #1e2937", borderRadius: 8, fontSize: 12 }}
          labelFormatter={fmt}
          formatter={(v, n) => [eur(v), n]} />
        <Line type="monotone" dataKey="total" stroke="#38bdf8" dot={false} strokeWidth={2} name="total cost" />
        <Line type="monotone" dataKey="lost" stroke="#fb923c" dot={false} strokeWidth={1} name="lost generation" />
        {naiveT && <ReferenceLine x={naiveT} stroke="#f43f5e" strokeDasharray="4 3"
          label={{ value: "naïve fix-now", fill: "#f43f5e", fontSize: 10, position: "insideTopRight" }} />}
        {chosenT && <ReferenceLine x={chosenT} stroke="#2dd4a7" strokeWidth={2}
          label={{ value: "chosen window", fill: "#2dd4a7", fontSize: 10, position: "insideTopLeft" }} />}
      </LineChart>
    </ResponsiveContainer>
  );
}

export default function IncidentDrawer({ data, onClose }) {
  const [tab, setTab] = useState("Diagnosis");
  if (!data) return null;
  const { diagnosis = {}, perception = {}, schedule = {}, work_order = {}, market = {} } = data;
  const attr = perception.attribution || [];

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <div className="drawer">
        <span className="close" onClick={onClose}>✕</span>
        <h3>{data.turbine_id} · {data.component.replace(/_/g, " ")}</h3>
        <div className="csub">
          Health {Math.round(data.health_score)} · {data.status} ·
          prognosis lead ~{perception.prognosis_lead_days}d ·
          P(failure) {(perception.p_failure_now * 100).toFixed(1)}% → {(perception.p_failure_horizon * 100).toFixed(1)}%
        </div>

        <div className="tabs">
          {TABS.map((t) => (
            <span key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</span>
          ))}
        </div>

        {tab === "Diagnosis" && (
          <>
            <div className="section">
              <div className="stitle">Root cause · Diagnostician agent</div>
              <div style={{ fontSize: 14, marginBottom: 6 }}>{diagnosis.root_cause}</div>
              <div className="muted" style={{ fontSize: 13 }}>{diagnosis.reasoning}</div>
              <div style={{ marginTop: 8, fontSize: 13 }}>
                <b>Confidence:</b> {(diagnosis.confidence * 100 || 0).toFixed(0)}% &nbsp;·&nbsp;
                <b>Action:</b> {diagnosis.recommended_action}
              </div>
            </div>
            <div className="section">
              <div className="stitle">SHAP-style signal attribution</div>
              {attr.map((a) => (
                <div key={a.signal} style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span>{a.signal.replace(/_/g, " ")}</span>
                    <span className="muted">weight {a.weight} · z {a.severity_z}</span>
                  </div>
                  <div className="attr-bar"><div style={{ width: `${a.weight * 100}%` }} /></div>
                </div>
              ))}
            </div>
            <div className="section">
              <div className="stitle">Grounding (RAG citations)</div>
              {(diagnosis.citations || []).map((c, i) => (
                <div className="cite" key={i}>▸ {c.source} (match {c.score})</div>
              ))}
            </div>
          </>
        )}

        {tab === "Economics" && (
          <>
            <div className="section">
              <div className="stitle">Cost-of-downtime curve · chosen vs. naïve window</div>
              <CostCurve curve={data.cost_curve || []}
                chosen={schedule.window_start} naive={schedule.naive_window_start} />
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                Prices: {market.source}. Optimiser: Google OR-Tools CP-SAT.
              </div>
            </div>
            <div className="section">
              <div className="compare">
                <div className="card">
                  <div className="muted" style={{ fontSize: 11 }}>NAÏVE FIX-NOW</div>
                  <div className="amt now">{eur(schedule.naive_total_cost_eur)}</div>
                </div>
                <div className="card">
                  <div className="muted" style={{ fontSize: 11 }}>OPTIMAL WINDOW</div>
                  <div className="amt opt">{eur(schedule.total_cost_eur)}</div>
                </div>
              </div>
              <div className="kv"><span className="k">Lost generation (chosen window)</span><span>{eur(schedule.lost_revenue_eur)}</span></div>
              <div className="kv"><span className="k">Expected failure risk cost</span><span>{eur(schedule.risk_cost_eur)}</span></div>
              <div className="kv"><span className="k">Generation revenue protected</span><span style={{ color: "var(--good)" }}>{eur(schedule.gen_revenue_protected_eur)}</span></div>
              <div className="kv"><span className="k">Unplanned-failure cost avoided</span><span style={{ color: "var(--good)" }}>{eur(schedule.failure_cost_avoided_eur)}</span></div>
              <div className="kv"><span className="k"><b>Total value protected</b></span><span style={{ color: "var(--good)", fontWeight: 700 }}>{eur(schedule.value_protected_eur)}</span></div>
            </div>
            <div className="section">
              <div className="stitle">Scheduler rationale</div>
              <div className="muted" style={{ fontSize: 13 }}>{schedule.agent_rationale || schedule.rationale}</div>
            </div>
          </>
        )}

        {tab === "Prognosis" && (
          <div className="section">
            <div className="stitle">Failure-probability trajectory (prognosis)</div>
            <ResponsiveContainer width="99%" height={220}>
              <AreaChart data={(data.prognosis_curve || []).map((p) => ({ day: p.day, p: p.p_failure * 100 }))}
                margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                <defs>
                  <linearGradient id="pf" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.6} />
                    <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1a2230" />
                <XAxis dataKey="day" stroke="#8696a7" fontSize={10} label={{ value: "days ahead", fill: "#8696a7", fontSize: 10, position: "insideBottom", dy: 10 }} />
                <YAxis stroke="#8696a7" fontSize={10} tickFormatter={(v) => v + "%"} />
                <Tooltip contentStyle={{ background: "#0e141e", border: "1px solid #1e2937", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => [v.toFixed(1) + "%", "P(failure)"]} />
                <Area type="monotone" dataKey="p" stroke="#f43f5e" fill="url(#pf)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              Lead time ~{perception.prognosis_lead_days} days to the failure threshold. The
              near-term hazard is nearly flat — which is exactly why the optimiser has the
              freedom to wait for a cheap, safe window.
            </div>
          </div>
        )}

        {tab === "Work order" && (
          <div className="section">
            <div className="stitle">{work_order.title}</div>
            <div style={{ marginBottom: 8 }}>
              <span className="tag">crew {schedule.crew}</span>
              <span className="tag">{work_order.estimated_downtime_h}h downtime</span>
              <span className="tag">part in stock: {work_order.part_in_stock}</span>
              <span className="tag">{work_order.status}</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Window: {fmtTime(schedule.window_start)}</div>
            <div className="stitle" style={{ marginTop: 12 }}>Parts</div>
            {(work_order.parts || []).map((p, i) => <div className="wo-step" key={i}>{p}</div>)}
            <div className="stitle" style={{ marginTop: 12 }}>Procedure</div>
            {(work_order.steps || []).map((s, i) => <div className="wo-step" key={i}>{s}</div>)}
            <div className="stitle" style={{ marginTop: 12 }}>Safety</div>
            {(work_order.safety || []).map((s, i) => <div className="wo-step" key={i}>{s}</div>)}
          </div>
        )}

        {tab === "Agent trace" && (
          <div className="section">
            <div className="stitle">Agent reasoning chain (LangGraph)</div>
            <div className="log">
              {(data.agent_log || []).map((l, i) => <div className="step" key={i}>{l}</div>)}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
