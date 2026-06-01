"""The cognition layer: a LangGraph stateful graph of five scoped agents.

    Orchestrator -> Diagnostician -> Market -> Scheduler -> Work-order -> finalize

Largely sequential by design (the blueprint's anti-chaos principle): each node is
an agent with scoped tools and a narrow job. Heavy computation already lives in
the Gold layer (perception, market curves, OR-Tools schedule); the agents reason
over those artefacts, ground themselves with RAG, and assemble a decision dossier.

Design principle, stated explicitly: the LLM reasons and explains; the OR-Tools
solver does the optimisation. The Scheduler agent never invents a window — it
reads the solver's answer and narrates the rationale.
"""
from __future__ import annotations

import json
import operator
from typing import Annotated, Any, TypedDict

import pandas as pd
from langgraph.graph import END, StateGraph

from aeolus import config as C
from aeolus.agents import llm, rag


class DossierState(TypedDict, total=False):
    incident: dict
    diagnosis: dict
    market: dict
    schedule: dict
    work_order: dict
    governance: dict
    log: Annotated[list, operator.add]


# ---------------------------------------------------------------------------
# Shared Gold loaders
# ---------------------------------------------------------------------------
def _schedule_for(tid: str) -> dict | None:
    sched = json.loads((C.GOLD_DIR / "schedule.json").read_text())
    for s in sched.get("schedule", []):
        if s["turbine_id"] == tid:
            return s
    return None


def _cost_curve_for(tid: str) -> pd.DataFrame:
    cost = pd.read_parquet(C.GOLD_DIR / "cost_of_downtime.parquet")
    return cost[cost["turbine_id"] == tid].sort_values("timestamp")


# ---------------------------------------------------------------------------
# Agents (graph nodes)
# ---------------------------------------------------------------------------
def orchestrator(state: DossierState) -> dict:
    inc = state["incident"]
    msg = (f"Orchestrator: fault on {inc['turbine_id']} "
           f"({inc['component']}, health {inc['health_score']}, "
           f"prognosis lead ~{inc.get('prognosis_lead_days')}d). "
           f"Routing -> Diagnostician -> Market -> Scheduler -> Work-order.")
    return {"log": [msg]}


def diagnostician(state: DossierState) -> dict:
    inc = state["incident"]
    top = inc.get("top_signal", "")
    attr = inc.get("attribution", [])
    query = (f"{inc['component']} {top} temperature residual rising overheating "
             f"failure mode diagnosis")
    refs = rag.search(query, k=4, component=inc["component"])
    ref_text = "\n".join(f"- ({r['source']}) {r['text'][:300]}" for r in refs)
    attr_text = ", ".join(f"{a['signal']} (weight {a['weight']})" for a in attr[:4])

    system = ("You are the Diagnostician agent in a wind-fleet operations brain. "
              "Root-cause the degradation from the SCADA residual attribution and "
              "the retrieved O&M references. Be specific and calibrated.")
    user = (f"Turbine {inc['turbine_id']} component '{inc['component']}'. "
            f"Anomaly residual z={inc['anomaly_z']} rising at {inc['trend_z_per_day']} "
            f"z/day; prognosis lead ~{inc.get('prognosis_lead_days')} days; "
            f"P(failure) now {inc['p_failure_now']} -> {inc.get('p_failure_horizon')} at horizon.\n"
            f"SHAP-style signal attribution: {attr_text}.\n"
            f"Retrieved O&M references:\n{ref_text}\n\n"
            "Return JSON with keys: root_cause (str), likely_component (str), "
            "confidence (0-1 float), reasoning (str, 2-3 sentences cite the signals), "
            "recommended_action (str).")
    fallback = {
        "root_cause": f"Progressive {inc['component'].replace('_',' ')} degradation — "
                      f"{top.replace('_',' ')} running hotter than conditions justify "
                      f"(grease/lubrication breakdown likely).",
        "likely_component": inc["component"],
        "confidence": round(min(0.95, 0.5 + inc["anomaly_z"] / 12.0), 2),
        "reasoning": (f"The normality model shows a sustained positive temperature "
                      f"residual (z={inc['anomaly_z']}) on {attr_text or top}, the "
                      f"classic early signature in the retrieved O&M reference."),
        "recommended_action": f"Plan a {inc['component'].replace('_',' ')} service in a "
                              f"low-generation safe-climb window before the residual escalates.",
    }
    diag = llm.chat_json(system, user, fallback=fallback)
    diag["citations"] = [{"source": r["source"], "score": r["score"]} for r in refs]
    return {"diagnosis": diag,
            "log": [f"Diagnostician [{llm.mode()}]: {diag['root_cause']} "
                    f"(confidence {diag.get('confidence')})"]}


def market_agent(state: DossierState) -> dict:
    inc = state["incident"]
    cc = _cost_curve_for(inc["turbine_id"])
    if cc.empty:
        return {"market": {}, "log": ["Market: no cost curve available"]}
    cheapest = cc.loc[cc["opportunity_cost_eur"].idxmin()]
    peak = cc.loc[cc["opportunity_cost_eur"].idxmax()]
    market = {
        "mean_opportunity_cost_eur_per_h": round(float(cc["opportunity_cost_eur"].mean()), 1),
        "cheapest_hour": {"timestamp": cheapest["timestamp"].isoformat(),
                          "opportunity_cost_eur": float(cheapest["opportunity_cost_eur"]),
                          "wind_ms": float(cheapest["wind_ms"]),
                          "price_eur_mwh": float(cheapest["price_eur_mwh"])},
        "peak_hour": {"timestamp": peak["timestamp"].isoformat(),
                      "opportunity_cost_eur": float(peak["opportunity_cost_eur"]),
                      "wind_ms": float(peak["wind_ms"]),
                      "price_eur_mwh": float(peak["price_eur_mwh"])},
        "source": "energy-charts.info (DE-LU day-ahead) + Open-Meteo",
    }
    msg = (f"Market: opportunity cost ranges €{peak['opportunity_cost_eur']:.0f}/h "
           f"(peak {peak['timestamp']:%a %H:%M}) to €{cheapest['opportunity_cost_eur']:.0f}/h "
           f"(cheapest {cheapest['timestamp']:%a %H:%M}) over the horizon.")
    return {"market": market, "log": [msg]}


def scheduler_agent(state: DossierState) -> dict:
    inc = state["incident"]
    s = _schedule_for(inc["turbine_id"])
    if not s:
        return {"schedule": {"scheduled": False,
                             "reason": "No feasible window this horizon (crew/weather/grid)."},
                "log": [f"Scheduler: {inc['turbine_id']} could not be scheduled this horizon."]}
    # the OR-Tools solver already chose the window; the agent only explains it
    system = ("You are the Scheduler agent. The OR-Tools solver has already chosen "
              "the cost-optimal maintenance window. Explain the decision crisply for "
              "an operations director. Do NOT change any numbers.")
    user = (f"Solver result: {json.dumps({k: s[k] for k in ['window_start','window_end','crew','total_cost_eur','lost_revenue_eur','risk_cost_eur','savings_eur','gen_revenue_protected_eur','failure_cost_avoided_eur']})}. "
            "Write a 2-sentence rationale.")
    narration = llm.chat(system, user, fallback=s["rationale"], max_tokens=200)
    s = dict(s)
    s["scheduled"] = True
    s["agent_rationale"] = narration
    return {"schedule": s,
            "log": [f"Scheduler [solver=OR-Tools]: {inc['turbine_id']} -> "
                    f"{s['window_start'][:16]} ({s['crew']}), value protected "
                    f"€{s['value_protected_eur']:,.0f}."]}


def workorder_agent(state: DossierState) -> dict:
    inc = state["incident"]
    diag = state.get("diagnosis", {})
    sched = state.get("schedule", {})
    parts = pd.read_parquet(C.SYNTHETIC_DIR / "parts_inventory.parquet")
    prow = parts[parts["component"] == inc["component"]]
    part_name = prow.iloc[0]["part_name"] if not prow.empty else f"{inc['component']} kit"
    in_stock = int(prow.iloc[0]["in_stock"]) if not prow.empty else 0
    lead = int(prow.iloc[0]["reorder_lead_days"]) if not prow.empty else 0

    refs = rag.search(f"{inc['component']} maintenance procedure parts crew safety", k=3)
    ref_text = "\n".join(f"- {r['text'][:240]}" for r in refs)

    system = ("You are the Work-order agent. Draft a concise, actionable maintenance "
              "work order grounded in the O&M references. Realistic and safe.")
    user = (f"Component: {inc['component']} on {inc['turbine_id']}. "
            f"Root cause: {diag.get('root_cause')}. "
            f"Window: {sched.get('window_start','TBD')} with crew {sched.get('crew','TBD')}. "
            f"Part: {part_name} (in stock: {in_stock}, reorder lead {lead} d).\n"
            f"O&M references:\n{ref_text}\n\n"
            "Return JSON: title (str), parts (list of str), steps (list of str, 4-6), "
            "safety (list of str, 2-3), estimated_downtime_h (int).")
    fallback = {
        "title": f"Planned {inc['component'].replace('_',' ')} service — {inc['turbine_id']}",
        "parts": [part_name, "Lubrication grease", "Replacement seals", "Sensor check kit"],
        "steps": [
            "Isolate turbine and apply lock-out/tag-out; confirm rotor locked.",
            f"Inspect {inc['component'].replace('_',' ')}; record temperatures and play.",
            "Drain/replace lubricant; replace seals; re-grease to spec.",
            "Verify sensor calibration; run controlled restart and monitor residuals.",
        ],
        "safety": ["Confirm wind < 12 m/s safe-climb envelope for the full window.",
                   "Two-person climb; full fall-arrest PPE; nacelle rescue kit on site."],
        "estimated_downtime_h": C.MAINTENANCE_HOURS.get(inc["component"], 8),
    }
    wo = llm.chat_json(system, user, fallback=fallback)
    wo["part_in_stock"] = in_stock
    wo["reorder_lead_days"] = lead
    wo["status"] = "DRAFT — awaiting human approval"
    return {"work_order": wo,
            "log": [f"Work-order [{llm.mode()}]: drafted '{wo.get('title')}' "
                    f"({wo.get('estimated_downtime_h')}h, part in stock: {in_stock})."]}


def finalize(state: DossierState) -> dict:
    return {"log": ["Orchestrator: dossier assembled, routing to governance gate."]}


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------
def build_graph():
    g = StateGraph(DossierState)
    g.add_node("orchestrator", orchestrator)
    g.add_node("diagnostician", diagnostician)
    g.add_node("market", market_agent)
    g.add_node("scheduler", scheduler_agent)
    g.add_node("workorder", workorder_agent)
    g.add_node("finalize", finalize)
    g.set_entry_point("orchestrator")
    g.add_edge("orchestrator", "diagnostician")
    g.add_edge("diagnostician", "market")
    g.add_edge("market", "scheduler")
    g.add_edge("scheduler", "workorder")
    g.add_edge("workorder", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


_GRAPH = None


def run_incident(incident: dict) -> dict:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    result = _GRAPH.invoke({"incident": incident, "log": []})
    return {
        "turbine_id": incident["turbine_id"],
        "component": incident["component"],
        "health_score": incident["health_score"],
        "status": incident["status"],
        "perception": {
            "anomaly_z": incident["anomaly_z"],
            "trend_z_per_day": incident["trend_z_per_day"],
            "prognosis_lead_days": incident.get("prognosis_lead_days"),
            "p_failure_now": incident["p_failure_now"],
            "p_failure_horizon": incident.get("p_failure_horizon"),
            "attribution": incident.get("attribution", []),
        },
        "diagnosis": result.get("diagnosis", {}),
        "market": result.get("market", {}),
        "schedule": result.get("schedule", {}),
        "work_order": result.get("work_order", {}),
        "agent_log": result.get("log", []),
    }


if __name__ == "__main__":
    incidents = json.loads((C.GOLD_DIR / "incidents.json").read_text())
    d = run_incident(incidents[0])
    print(json.dumps(d, indent=2, default=str)[:1500])
