"""AEOLUS API — serves fleet operations state to the dashboard.

Reads the Gold artefacts produced by the pipeline and exposes them as JSON, plus
the human-in-the-loop actions (approve/reject), the kill switch, and the audit
trail. Run:  uvicorn aeolus.api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import threading
import time

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from aeolus import config as C
from aeolus.agents import llm
from aeolus.governance import audit, gate

app = FastAPI(title="AEOLUS — Autonomous Operations Brain", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def _read_json(name: str, default):
    p = C.GOLD_DIR / name
    return json.loads(p.read_text()) if p.exists() else default


# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "site": C.SITE, "llm_mode": llm.mode(),
            "llm_model": C.LLM_MODEL or None}


@app.get("/api/fleet")
def fleet():
    """Turbine map + health + live wind for the animated fleet view."""
    turbines = pd.read_parquet(C.SILVER_DIR / "turbines.parquet")
    health = pd.read_parquet(C.GOLD_DIR / "turbine_health.parquet")
    df = turbines.merge(health, on="turbine_id", how="left")
    df["health_score"] = df["health_score"].fillna(100.0)
    df["status"] = df["status"].fillna("healthy")

    # current hub-height wind per turbine (drives blade rotation on the dashboard)
    wpath = C.GOLD_DIR / "weather_forecast.parquet"
    if wpath.exists():
        w = pd.read_parquet(wpath)
        w["timestamp"] = pd.to_datetime(w["timestamp"], utc=True)
        now = pd.Timestamp.now(tz="UTC")
        w["dist"] = (w["timestamp"] - now).abs()
        cur = (w.sort_values("dist").groupby("turbine_id")
               .agg(wind_ms=("wind_ms", "first")).reset_index())
        df = df.merge(cur, on="turbine_id", how="left")
    else:
        df["wind_ms"] = 8.0
    df["wind_ms"] = df["wind_ms"].fillna(8.0).round(1)
    # expected power now, from the fitted power curve (nice for the scene HUD)
    try:
        from aeolus.perception import models as Mp
        df["expected_power_kw"] = [round(float(Mp.expected_power_kw(t, wv)), 0)
                                   for t, wv in zip(df["turbine_id"], df["wind_ms"])]
    except Exception:
        df["expected_power_kw"] = 0.0
    approvals = _read_json("approvals.json", {})
    return {
        "site": C.SITE,
        "turbines": json.loads(df.to_json(orient="records")),
        "realized_value_protected_eur": approvals.get("realized_value_protected_eur", 0.0),
        "potential_value_protected_eur": approvals.get("potential_value_protected_eur", 0.0),
        "kill_switch": gate.kill_switch_active(),
    }


@app.get("/api/incidents")
def incidents():
    return _read_json("dossiers.json", [])


@app.get("/api/incident/{turbine_id}")
def incident(turbine_id: str):
    dossiers = _read_json("dossiers.json", [])
    d = next((x for x in dossiers if x["turbine_id"] == turbine_id), None)
    if not d:
        raise HTTPException(404, "No incident for this turbine")
    # attach the candidate cost-of-downtime curve for the drawer chart
    sched = _read_json("schedule.json", {})
    d = dict(d)
    d["cost_curve"] = sched.get("candidate_curves", {}).get(turbine_id, [])
    d["prognosis_curve"] = _prognosis_for(turbine_id)
    d["residual_series"] = _residuals_for(turbine_id)
    return d


def _prognosis_for(tid: str):
    p = C.GOLD_DIR / "prognosis_curves.parquet"
    if not p.exists():
        return []
    df = pd.read_parquet(p)
    return json.loads(df[df["turbine_id"] == tid].to_json(orient="records"))


def _residuals_for(tid: str):
    p = C.GOLD_DIR / "residual_series.parquet"
    if not p.exists():
        return []
    df = pd.read_parquet(p)
    return json.loads(df[df["turbine_id"] == tid].to_json(orient="records"))


@app.get("/api/approvals")
def approvals():
    return _read_json("approvals.json", {"queue": []})


class Decision(BaseModel):
    approve: bool
    approver: str = "ops-director"
    note: str = ""


@app.post("/api/approvals/{action_id}/decide")
def decide(action_id: str, body: Decision):
    try:
        return gate.decide(action_id, body.approve, body.approver, body.note)
    except KeyError:
        raise HTTPException(404, "Unknown action id")
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/audit")
def audit_log():
    return {"entries": audit.read_all(), "verification": audit.verify_chain()}


class Kill(BaseModel):
    active: bool


@app.post("/api/kill-switch")
def kill_switch(body: Kill):
    gate.set_kill_switch(body.active)
    return {"kill_switch": gate.kill_switch_active()}


@app.get("/api/market/{turbine_id}")
def market(turbine_id: str):
    cost = pd.read_parquet(C.GOLD_DIR / "cost_of_downtime.parquet")
    cost = cost[cost["turbine_id"] == turbine_id].sort_values("timestamp")
    return json.loads(cost.to_json(orient="records"))


# ---------------------------------------------------------------------------
# Scheduler — periodically re-runs the LIVE layers (weather + market + re-optimise)
# so the economics refresh against the moving market. Human approvals are
# preserved across refreshes (build_approval_queue(preserve=True)).
# ---------------------------------------------------------------------------
_sched = {"running": False, "last_run": None, "last_duration_s": None,
          "interval_s": int(os.environ.get("AEOLUS_REFRESH_SECONDS", "180")),
          "last_error": None}
_sched_lock = threading.Lock()


def _refresh() -> bool:
    with _sched_lock:
        if _sched["running"]:
            return False
        _sched["running"] = True
    t0 = time.time()
    try:
        from aeolus.lakehouse import synthetic as synth_mod
        from aeolus.market import market as market_mod
        from aeolus.optimizer import scheduler as sched_mod
        start, hours = market_mod.get_horizon()
        market_mod.run()                                   # live Open-Meteo + prices
        synth_mod.run(horizon_start=start.normalize(), days=hours // 24 + 3)
        sched_mod.optimise()                               # re-optimise schedule
        gate.build_approval_queue(preserve=True)           # keep human decisions
        _sched["last_error"] = None
    except Exception as e:                                 # never crash the loop
        _sched["last_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        _sched["last_run"] = pd.Timestamp.now(tz="UTC").isoformat()
        _sched["last_duration_s"] = round(time.time() - t0, 1)
        _sched["running"] = False
    return True


def _loop() -> None:
    while True:
        time.sleep(_sched["interval_s"])
        if os.environ.get("AEOLUS_SCHEDULER", "1") != "0":
            _refresh()


@app.on_event("startup")
def _start_scheduler() -> None:
    if os.environ.get("AEOLUS_SCHEDULER", "1") != "0":
        threading.Thread(target=_loop, daemon=True).start()


@app.get("/api/pipeline/status")
def pipeline_status():
    return {**_sched,
            "scheduler_enabled": os.environ.get("AEOLUS_SCHEDULER", "1") != "0"}


@app.post("/api/pipeline/run")
def pipeline_run():
    if _sched["running"]:
        raise HTTPException(409, "A refresh is already running")
    threading.Thread(target=_refresh, daemon=True).start()
    return {"started": True}


# Serve the built frontend (single-service Docker deploy). Mounted LAST so it
# never shadows the /api routes above.
_DIST = C.PROJECT_DIR / "frontend" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
