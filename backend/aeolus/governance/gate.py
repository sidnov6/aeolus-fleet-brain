"""Governance gate: policy engine + digital-twin sim + human approval + kill switch.

Every proposed maintenance action passes this gate before anything happens:
  1. Policy engine (OPA-style autonomy boundaries) — auto-approve vs. escalate by
     cost and risk thresholds.
  2. Digital-twin / simulation pre-check — confirm taking the turbine down in the
     chosen window won't breach a firm grid commitment.
  3. Human approval gate — technically enforced: high-risk actions cannot proceed
     un-reviewed (status stays 'pending_human').
  4. Immutable audit log — every proposal + decision is hash-chained.
  5. Kill switch — a flag file halts all agent action fleet-wide.
"""
from __future__ import annotations

import json

import pandas as pd

from aeolus import config as C
from aeolus.governance import audit


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------
def kill_switch_active() -> bool:
    return C.KILL_SWITCH_FILE.exists()


def set_kill_switch(active: bool) -> bool:
    if active:
        C.KILL_SWITCH_FILE.write_text(pd.Timestamp.now(tz="UTC").isoformat())
        audit.append("KILL_SWITCH_ENGAGED", {"scope": "fleet-wide"})
    else:
        if C.KILL_SWITCH_FILE.exists():
            C.KILL_SWITCH_FILE.unlink()
        audit.append("KILL_SWITCH_RELEASED", {"scope": "fleet-wide"})
    return active


# ---------------------------------------------------------------------------
# 1. Policy engine (OPA-style)
# ---------------------------------------------------------------------------
def policy_check(dossier: dict) -> dict:
    sched = dossier.get("schedule", {})
    perc = dossier.get("perception", {})
    cost = float(sched.get("total_cost_eur", 0.0))
    risk = float(perc.get("p_failure_horizon") or perc.get("p_failure_now") or 0.0)

    reasons = []
    if cost > C.AUTO_APPROVE_MAX_COST_EUR:
        reasons.append(f"Expected cost €{cost:,.0f} exceeds auto-approve ceiling "
                       f"€{C.AUTO_APPROVE_MAX_COST_EUR:,.0f}.")
    if risk > C.AUTO_APPROVE_MAX_RISK:
        reasons.append(f"Failure probability {risk:.0%} exceeds auto-approve ceiling "
                       f"{C.AUTO_APPROVE_MAX_RISK:.0%}.")
    # any physical intervention on a high-value asset escalates by default
    reasons.append("Physical intervention on a high-value asset — EU AI Act "
                   "high-risk class requires human sign-off.")
    return {"auto_approvable": len(reasons) <= 1 and cost <= C.AUTO_APPROVE_MAX_COST_EUR
            and risk <= C.AUTO_APPROVE_MAX_RISK,
            "requires_human": True, "reasons": reasons,
            "thresholds": {"max_cost_eur": C.AUTO_APPROVE_MAX_COST_EUR,
                           "max_risk": C.AUTO_APPROVE_MAX_RISK}}


# ---------------------------------------------------------------------------
# 2. Digital-twin simulation pre-check
# ---------------------------------------------------------------------------
def sim_precheck(dossier: dict) -> dict:
    """Simulate the proposed downtime against firm grid commitments.

    Confirms that with this turbine offline during the window, the rest of the
    fleet still meets every overlapping min-aggregate grid commitment (using the
    live generation forecast).
    """
    sched = dossier.get("schedule", {})
    if not sched.get("scheduled"):
        return {"passed": False, "reason": "No scheduled window to simulate."}
    tid = dossier["turbine_id"]
    start = pd.Timestamp(sched["window_start"])
    end = pd.Timestamp(sched["window_end"])

    weather = pd.read_parquet(C.GOLD_DIR / "weather_forecast.parquet")
    weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
    grid = pd.read_parquet(C.SYNTHETIC_DIR / "grid_commitments.parquet")

    from aeolus.perception import models as M
    breaches = []
    for g in grid.itertuples():
        gs = pd.Timestamp(g.start); ge = pd.Timestamp(g.end)
        gs = gs.tz_localize("UTC") if gs.tzinfo is None else gs
        ge = ge.tz_localize("UTC") if ge.tzinfo is None else ge
        if not (start < ge and end > gs):
            continue  # window doesn't overlap this commitment
        # fleet expected MW during the overlap, excluding the down turbine
        overlap = weather[(weather["timestamp"] >= max(start, gs)) &
                          (weather["timestamp"] < min(end, ge))]
        total_mw = []
        for ts, w in overlap.groupby("timestamp"):
            mw = 0.0
            for r in w.itertuples():
                if r.turbine_id == tid:
                    continue
                mw += float(M.expected_power_kw(r.turbine_id, r.wind_ms)) / 1000.0
            total_mw.append(mw)
        min_fleet = min(total_mw) if total_mw else 999.0
        if min_fleet < g.min_aggregate_mw:
            breaches.append({"commitment_id": g.commitment_id,
                             "required_mw": float(g.min_aggregate_mw),
                             "available_mw": round(min_fleet, 2)})
    passed = len(breaches) == 0
    return {"passed": passed,
            "breaches": breaches,
            "reason": ("No firm grid commitment is breached by this window."
                       if passed else "Window would breach a grid commitment.")}


# ---------------------------------------------------------------------------
# Build the approval queue from dossiers
# ---------------------------------------------------------------------------
def build_approval_queue(preserve: bool = False) -> dict:
    dossiers = json.loads((C.GOLD_DIR / "dossiers.json").read_text())
    schedule = json.loads((C.GOLD_DIR / "schedule.json").read_text())

    # carry over prior human decisions across a refresh (don't wipe approvals)
    prior = {}
    appr_path = C.GOLD_DIR / "approvals.json"
    if preserve and appr_path.exists():
        try:
            for q in json.loads(appr_path.read_text()).get("queue", []):
                if q.get("status") in ("approved", "rejected"):
                    prior[q["id"]] = {"status": q["status"], "approved_by": q.get("approved_by")}
        except Exception:
            prior = {}

    is_refresh = bool(preserve)
    if is_refresh:
        audit.append("PIPELINE_REFRESH", {"n_incidents": len(dossiers),
                                          "horizon_start": schedule.get("horizon_start"),
                                          "preserved_decisions": len(prior)})
    else:
        audit.reset()
        audit.append("PIPELINE_RUN", {"n_incidents": len(dossiers),
                                      "horizon_start": schedule.get("horizon_start")})

    queue = []
    realized = 0.0
    potential = 0.0
    for i, d in enumerate(dossiers):
        policy = policy_check(d)
        sim = sim_precheck(d)
        sched = d.get("schedule", {})
        value = float(sched.get("value_protected_eur", 0.0))
        potential += value
        # a high-risk action can only proceed once a human approves AND sim passes
        status = "pending_human"
        if not sched.get("scheduled"):
            status = "blocked_no_window"
        elif not sim["passed"]:
            status = "blocked_sim"

        action_id = f"WO-{d['turbine_id']}-{i+1:03d}"
        approved_by = None
        if action_id in prior:                       # carry over a prior decision
            status = prior[action_id]["status"]
            approved_by = prior[action_id]["approved_by"]
            if status == "approved":
                realized += value
        item = {
            "id": action_id,
            "turbine_id": d["turbine_id"],
            "component": d["component"],
            "status": status,
            "approved_by": approved_by,
            "value_protected_eur": value,
            "policy": policy,
            "sim": sim,
            "diagnosis_confidence": d.get("diagnosis", {}).get("confidence"),
            "work_order_title": d.get("work_order", {}).get("title"),
            "window_start": sched.get("window_start"),
            "crew": sched.get("crew"),
        }
        queue.append(item)
        if not is_refresh:
            audit.append("ACTION_PROPOSED", {
            "id": item["id"], "turbine_id": d["turbine_id"], "component": d["component"],
            "root_cause": d.get("diagnosis", {}).get("root_cause"),
            "confidence": d.get("diagnosis", {}).get("confidence"),
            "chosen_window": sched.get("window_start"),
            "alternatives_considered": "full hourly cost-of-downtime curve over horizon",
            "value_protected_eur": value,
            "policy_decision": "escalate_to_human" if policy["requires_human"] else "auto",
            "sim_passed": sim["passed"],
        })

    state = {
        "queue": queue,
        "realized_value_protected_eur": round(realized, 1),
        "potential_value_protected_eur": round(potential, 1),
        "kill_switch": kill_switch_active(),
        "audit_chain": audit.verify_chain(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (C.GOLD_DIR / "approvals.json").write_text(json.dumps(state, indent=2, default=str))
    print(f"  governance: {len(queue)} action(s) queued; "
          f"potential value protected €{potential:,.0f}; "
          f"audit chain valid={state['audit_chain']['valid']}")
    return state


# ---------------------------------------------------------------------------
# Approve / reject (called by the API)
# ---------------------------------------------------------------------------
def decide(action_id: str, approve: bool, approver: str, note: str = "") -> dict:
    state = json.loads((C.GOLD_DIR / "approvals.json").read_text())
    if kill_switch_active():
        audit.append("ACTION_BLOCKED_KILLSWITCH", {"id": action_id})
        raise RuntimeError("Kill switch is engaged — no action can proceed.")

    item = next((q for q in state["queue"] if q["id"] == action_id), None)
    if item is None:
        raise KeyError(action_id)

    if approve:
        if not item["sim"]["passed"]:
            raise RuntimeError("Cannot approve: digital-twin sim pre-check failed.")
        item["status"] = "approved"
        item["approved_by"] = approver
        state["realized_value_protected_eur"] = round(
            float(state["realized_value_protected_eur"]) + float(item["value_protected_eur"]), 1)
        audit.append("ACTION_APPROVED",
                     {"id": action_id, "approver": approver, "note": note,
                      "value_protected_eur": item["value_protected_eur"]})
    else:
        item["status"] = "rejected"
        item["approved_by"] = approver
        # rejection is a training signal (blueprint): feeds back to tune the policy
        audit.append("ACTION_REJECTED",
                     {"id": action_id, "approver": approver, "note": note,
                      "training_signal": True})

    state["audit_chain"] = audit.verify_chain()
    (C.GOLD_DIR / "approvals.json").write_text(json.dumps(state, indent=2, default=str))
    return state


if __name__ == "__main__":
    build_approval_queue()
