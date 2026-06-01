"""The optimization core (the differentiator).

The Scheduler chooses a maintenance window start t* per incident over a rolling
hourly horizon to minimise total expected cost:

    minimise   C(t) = LostRevenue(t) + RiskCost(t)
      LostRevenue(t) = Σ_{h in [t, t+duration)} price(h) · E[power(h)]
      RiskCost(t)    = P_failure(t) · CostOfUnplannedFailure
    subject to
      (1) a skilled crew is available in window t           (assignment + no-overlap)
      (2) wind inside window t ≤ safe-climb envelope         (hard)
      (3) no firm grid commitment is violated during t       (hard)

Design principle (stated explicitly in the write-up): the LLM reasons and
explains; OR-Tools does the optimisation. We never ask a language model to do the
math. This is a genuine CP-SAT model — multiple incidents compete for shared
crews via optional-interval no-overlap, not a hand-rolled argmin.

The naïve "fix-it-now" baseline (earliest feasible window, ignoring the market) is
solved too; the difference is the revenue-protected figure — the money shot.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

from aeolus import config as C


def _load_inputs():
    incidents = json.loads((C.GOLD_DIR / "incidents.json").read_text())
    cost = pd.read_parquet(C.GOLD_DIR / "cost_of_downtime.parquet")
    cost["timestamp"] = pd.to_datetime(cost["timestamp"], utc=True)
    weather = pd.read_parquet(C.GOLD_DIR / "weather_forecast.parquet")
    weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
    crew = pd.read_parquet(C.SYNTHETIC_DIR / "crew_roster.parquet")
    grid = pd.read_parquet(C.SYNTHETIC_DIR / "grid_commitments.parquet")
    prog = pd.read_parquet(C.GOLD_DIR / "prognosis_curves.parquet")
    return incidents, cost, weather, crew, grid, prog


def _p_failure_at(prog: pd.DataFrame, tid: str, day_offset: float) -> float:
    sub = prog[prog["turbine_id"] == tid].sort_values("day")
    if sub.empty:
        return 0.0
    return float(np.interp(day_offset, sub["day"], sub["p_failure"]))


def _build_options(incidents, cost, weather, crew, grid, prog, horizon_start):
    """Enumerate feasible (incident, start_hour, crew) options with their cost."""
    cost_p = cost.pivot_table(index="timestamp", columns="turbine_id",
                              values="opportunity_cost_eur")
    wind_p = weather.pivot_table(index="timestamp", columns="turbine_id",
                                 values="wind_ms")
    hours = cost_p.index.sort_values()

    grid_blocks = [(pd.Timestamp(r.start, tz="UTC") if r.start.tzinfo is None else r.start,
                    pd.Timestamp(r.end, tz="UTC") if r.end.tzinfo is None else r.end)
                   for r in grid.itertuples()]

    def grid_ok(t0, t1):
        return not any(t0 < gb_end and t1 > gb_start for gb_start, gb_end in grid_blocks)

    options = []          # dicts with incident idx, crew, start, end, cost parts
    per_incident_curve = {}

    for idx, inc in enumerate(incidents):
        tid = inc["turbine_id"]
        comp = inc["component"]
        dur = C.MAINTENANCE_HOURS.get(comp, 8)
        unplanned = C.UNPLANNED_FAILURE_COST.get(comp, 150_000.0)
        skilled_crews = crew[crew["skills"].str.contains(comp)]["crew_id"].unique().tolist()

        curve = []
        for t in hours:
            window = pd.date_range(t, periods=dur, freq="h", tz="UTC")
            t_end = t + pd.Timedelta(hours=dur)
            if window[-1] not in cost_p.index:
                continue
            # (1) start within working hours
            if not (7 <= t.hour <= 16):
                continue
            # (2) safe-climb: wind under envelope across the whole window
            winds = wind_p.loc[window, tid] if tid in wind_p else pd.Series([np.nan])
            if winds.isna().any() or (winds > C.SAFE_CLIMB_MAX_WIND_MS).any():
                weather_ok = False
            else:
                weather_ok = True
            # (3) grid commitments
            g_ok = grid_ok(t, t_end)

            lost_rev = float(cost_p.loc[window, tid].sum())
            day_off = (t - horizon_start).total_seconds() / 86400.0
            p_fail = _p_failure_at(prog, tid, day_off)
            risk_cost = p_fail * unplanned
            total = lost_rev + risk_cost

            feasible = weather_ok and g_ok
            curve.append({
                "start": t.isoformat(), "day_offset": round(day_off, 2),
                "lost_revenue_eur": round(lost_rev, 1),
                "p_failure": round(p_fail, 4),
                "risk_cost_eur": round(risk_cost, 1),
                "total_cost_eur": round(total, 1),
                "weather_ok": weather_ok, "grid_ok": g_ok, "feasible": feasible,
                "max_wind_ms": round(float(winds.max()) if not winds.isna().all() else 99, 1),
            })

            if not feasible:
                continue
            for c_id in skilled_crews:
                day = t.normalize()
                roster = crew[(crew["crew_id"] == c_id) & (crew["date"] == day)]
                if roster.empty or not bool(roster.iloc[0]["available"]):
                    continue
                shift_start = pd.Timestamp(roster.iloc[0]["shift_start"])
                if shift_start.tzinfo is None:
                    shift_start = shift_start.tz_localize("UTC")
                if t < shift_start:
                    continue
                options.append({
                    "incident": idx, "turbine_id": tid, "component": comp,
                    "crew": c_id, "start": t, "end": t_end, "dur": dur,
                    "lost_revenue": lost_rev, "risk_cost": risk_cost,
                    "p_failure": p_fail, "total": total,
                })
        per_incident_curve[tid] = curve

    return options, per_incident_curve, hours


def _solve(options, n_incidents):
    """CP-SAT: pick one option per incident; no crew double-booking; min cost."""
    model = cp_model.CpModel()
    # decision var per option
    choose = [model.NewBoolVar(f"opt_{i}") for i in range(len(options))]

    # exactly one option per incident
    for inc in range(n_incidents):
        idxs = [i for i, o in enumerate(options) if o["incident"] == inc]
        if idxs:
            model.Add(sum(choose[i] for i in idxs) == 1)

    # per-crew no-overlap via optional intervals
    H = 3600
    crews = {o["crew"] for o in options}
    horizon_min = min(int(o["start"].value) for o in options) if False else 0
    base = min(o["start"] for o in options)
    for c_id in crews:
        intervals = []
        for i, o in enumerate(options):
            if o["crew"] != c_id:
                continue
            s = int((o["start"] - base).total_seconds())
            e = int((o["end"] - base).total_seconds())
            iv = model.NewOptionalIntervalVar(s, e - s, e, choose[i], f"iv_{i}")
            intervals.append(iv)
        if intervals:
            model.AddNoOverlap(intervals)

    # objective: minimise total cost (scaled to int EUR)
    model.Minimize(sum(int(round(o["total"])) * choose[i] for i, o in enumerate(options)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status
    chosen = [options[i] for i in range(len(options)) if solver.Value(choose[i]) == 1]
    return chosen, status


def _naive_baseline(options, n_incidents):
    """Fix-it-now: earliest feasible window per incident, greedy crew assignment."""
    chosen, used = [], {}
    for inc in range(n_incidents):
        opts = sorted((o for o in options if o["incident"] == inc),
                      key=lambda o: o["start"])
        for o in opts:
            clash = any(c["crew"] == o["crew"] and not (o["end"] <= c["start"] or o["start"] >= c["end"])
                        for c in chosen)
            if not clash:
                chosen.append(o)
                break
    return chosen


def optimise() -> dict:
    incidents, cost, weather, crew, grid, prog = _load_inputs()
    if not incidents:
        print("  no incidents to schedule")
        return {"schedule": [], "revenue_protected_eur": 0.0}
    horizon_start = cost["timestamp"].min()

    options, curves, hours = _build_options(
        incidents, cost, weather, crew, grid, prog, horizon_start)
    if not options:
        print("  [warn] no feasible options found")
        return {"schedule": [], "revenue_protected_eur": 0.0}

    chosen, status = _solve(options, len(incidents))
    naive = _naive_baseline(options, len(incidents))

    # incidents with zero feasible options can't be scheduled this horizon
    unscheduled = []
    for idx, inc in enumerate(incidents):
        if not any(o["incident"] == idx for o in options):
            unscheduled.append({
                "turbine_id": inc["turbine_id"], "component": inc["component"],
                "reason": "No window satisfies crew availability + safe-climb wind "
                          "+ grid-commitment constraints within the horizon.",
            })

    opt_total = sum(o["total"] for o in chosen)
    naive_total = sum(o["total"] for o in naive)
    revenue_protected = max(0.0, naive_total - opt_total)

    # Headline economics, broken into two honest components:
    #  (1) generation revenue protected = lost-gen avoided by scheduling the
    #      downtime in the cheapest safe window instead of the naive first slot.
    #  (2) failure cost avoided = value of acting on the prognosis at all, i.e.
    #      a PLANNED intervention now vs. an expected UNPLANNED failure later:
    #          P_failure_horizon * (UnplannedCost - PlannedCost)
    gen_revenue_protected = 0.0
    failure_cost_avoided = 0.0
    inc_by_idx = {i: inc for i, inc in enumerate(incidents)}

    schedule = []
    naive_by_inc = {o["incident"]: o for o in naive}
    for o in chosen:
        inc = inc_by_idx[o["incident"]]
        nv = naive_by_inc.get(o["incident"], o)
        unplanned = C.UNPLANNED_FAILURE_COST.get(o["component"], 150_000.0)
        planned = unplanned * C.PLANNED_COST_FRACTION
        p_horizon = float(inc.get("p_failure_horizon", inc.get("p_failure_now", 0.0)))
        fca = p_horizon * (unplanned - planned)
        gen_revenue_protected += max(0.0, nv["lost_revenue"] - o["lost_revenue"])
        failure_cost_avoided += fca
        schedule.append({
            "turbine_id": o["turbine_id"], "component": o["component"],
            "crew": o["crew"],
            "window_start": o["start"].isoformat(), "window_end": o["end"].isoformat(),
            "duration_h": o["dur"],
            "lost_revenue_eur": round(o["lost_revenue"], 1),
            "risk_cost_eur": round(o["risk_cost"], 1),
            "p_failure_at_window": round(o["p_failure"], 4),
            "total_cost_eur": round(o["total"], 1),
            "naive_window_start": nv["start"].isoformat(),
            "naive_total_cost_eur": round(nv["total"], 1),
            "naive_lost_revenue_eur": round(nv["lost_revenue"], 1),
            "savings_eur": round(nv["total"] - o["total"], 1),
            "gen_revenue_protected_eur": round(max(0.0, nv["lost_revenue"] - o["lost_revenue"]), 1),
            "planned_cost_eur": round(planned, 1),
            "unplanned_cost_eur": round(unplanned, 1),
            "p_failure_horizon": round(p_horizon, 4),
            "failure_cost_avoided_eur": round(fca, 1),
            "value_protected_eur": round(max(0.0, nv["lost_revenue"] - o["lost_revenue"]) + fca, 1),
            "rationale": (
                f"Scheduled {o['component'].replace('_',' ')} service on {o['turbine_id']} "
                f"at {o['start']:%a %d %b %H:%M} UTC with {o['crew']}. This window costs "
                f"€{o['total']:,.0f} (€{o['lost_revenue']:,.0f} lost generation + "
                f"€{o['risk_cost']:,.0f} expected failure risk) versus €{nv['total']:,.0f} "
                f"for fixing it at the first available slot — saving €{nv['total']-o['total']:,.0f}. "
                f"Wind stays within the {C.SAFE_CLIMB_MAX_WIND_MS} m/s safe-climb envelope and no "
                f"firm grid commitment is breached."
            ),
        })

    out = {
        "horizon_start": horizon_start.isoformat(),
        "solver_status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        "schedule": schedule,
        "unscheduled": unscheduled,
        "optimal_total_cost_eur": round(opt_total, 1),
        "naive_total_cost_eur": round(naive_total, 1),
        "revenue_protected_eur": round(revenue_protected, 1),
        # headline counter (the money shot), broken down honestly
        "gen_revenue_protected_eur": round(gen_revenue_protected, 1),
        "failure_cost_avoided_eur": round(failure_cost_avoided, 1),
        "value_protected_eur": round(gen_revenue_protected + failure_cost_avoided, 1),
        "candidate_curves": curves,
    }
    (C.GOLD_DIR / "schedule.json").write_text(json.dumps(out, indent=2))
    print(f"  optimiser [{out['solver_status']}]: scheduled {len(schedule)} job(s); "
          f"value protected €{out['value_protected_eur']:,.0f} "
          f"(generation €{gen_revenue_protected:,.0f} + failure-cost avoided "
          f"€{failure_cost_avoided:,.0f})")
    for s in schedule:
        print(f"    {s['turbine_id']} {s['component']}: {s['window_start'][:16]} "
              f"({s['crew']}) save €{s['savings_eur']:,.0f}")
    for u in unscheduled:
        print(f"    [unscheduled] {u['turbine_id']} {u['component']}: {u['reason']}")
    return out


if __name__ == "__main__":
    optimise()
