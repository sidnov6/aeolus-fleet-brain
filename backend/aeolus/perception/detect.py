"""Anomaly + prognosis + explainability -> Gold feature store and incidents.

From the standardized temperature residuals we derive, per turbine:
  - a per-component health score (0-100) from smoothed positive residual drift,
  - a turbine health score (worst component governs),
  - a prognosis lead-time: fit the residual trend and extrapolate to a failure
    threshold to estimate days-to-failure and a rising P_failure(t) hazard curve,
  - a SHAP-style attribution: which signals drove the flag (ranked contribution).

These are the artefacts the cognition layer consumes: the Diagnostician reads the
attribution, the Market/Scheduler read the P_failure(t) curve.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from aeolus import config as C
from aeolus.perception import models as M

RECENT_DAYS = 60          # window we assess for current health
TREND_DAYS = 42           # window used to fit the degradation trend
HORIZON_DAYS = 14         # prognosis horizon
Z_FAIL = 8.0              # residual-z deemed "failure imminent"

# map each component to its temperature signals
_COMP_SIGNALS: dict[str, list[str]] = {}
for _sig, _comp in C.TEMP_TARGETS.items():
    _COMP_SIGNALS.setdefault(_comp, []).append(_sig)


def _status(score: float) -> str:
    if score >= 85: return "healthy"
    if score >= 70: return "watch"
    if score >= 45: return "degrading"
    return "critical"


def _daily_z(df: pd.DataFrame, sig: str) -> pd.Series:
    col = f"{sig}_resid_z"
    if col not in df:
        return pd.Series(dtype=float)
    s = df.set_index("timestamp")[col].dropna()
    return s.resample("1D").mean().dropna()


def _severity(daily: pd.Series) -> float:
    """Recent smoothed positive drift (EWMA of clipped-positive daily z)."""
    if daily.empty:
        return 0.0
    pos = daily.clip(lower=0)
    return float(pos.ewm(span=10).mean().iloc[-1])


def _trend(daily: pd.Series) -> tuple[float, float]:
    """(z_now, slope_per_day) from a robust linear fit over the trend window."""
    if len(daily) < 5:
        return (float(daily.iloc[-1]) if len(daily) else 0.0, 0.0)
    tail = daily.iloc[-TREND_DAYS:]
    x = (tail.index - tail.index[0]).days.to_numpy(dtype=float)
    y = tail.to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    z_now = float(slope * x[-1] + intercept)
    return z_now, float(slope)


def _p_failure_curve(z_now: float, slope: float) -> list[dict]:
    curve = []
    for h in range(0, HORIZON_DAYS + 1):
        z_proj = z_now + slope * h
        # shallow hazard: stays low while the residual is modest and only climbs
        # steeply near the failure threshold. For a long-lead incident this makes
        # the near-term (days) failure probability nearly flat — which is exactly
        # why the optimiser has the freedom to shop for a cheap, safe window.
        p = 1.0 / (1.0 + np.exp(-0.45 * (z_proj - 11.0)))
        curve.append({"day": h, "z_proj": round(z_proj, 3), "p_failure": round(float(p), 4)})
    return curve


def assess() -> dict:
    scada = pd.read_parquet(C.SILVER_DIR / "scada_scenario.parquet")
    scada["timestamp"] = pd.to_datetime(scada["timestamp"], utc=True)
    scada = M.predict_residuals(scada)

    end = scada["timestamp"].max()
    recent_start = end - pd.Timedelta(days=RECENT_DAYS)

    turbine_rows, incidents, prognosis_rows, series_rows = [], [], [], []

    for tid, df in scada.groupby("turbine_id"):
        df = df.sort_values("timestamp")
        recent = df[df["timestamp"] >= recent_start]

        comp_scores = {}
        comp_detail = {}
        for comp, sigs in _COMP_SIGNALS.items():
            sev_by_sig = {}
            for sig in sigs:
                daily = _daily_z(recent, sig)
                sev_by_sig[sig] = _severity(daily)
            sev = max(sev_by_sig.values()) if sev_by_sig else 0.0
            score = max(0.0, 100.0 - 14.0 * sev)
            comp_scores[comp] = score
            comp_detail[comp] = sev_by_sig

        worst_comp = min(comp_scores, key=comp_scores.get)
        health = comp_scores[worst_comp]
        status = _status(health)

        # prognosis on the worst signal of the worst component
        worst_sig = max(comp_detail[worst_comp], key=comp_detail[worst_comp].get)
        daily_worst = _daily_z(recent, worst_sig)
        z_now, slope = _trend(daily_worst)
        pf_curve = _p_failure_curve(z_now, slope)
        p_now = pf_curve[0]["p_failure"]
        # lead time to Z_FAIL
        if slope > 1e-3 and z_now < Z_FAIL:
            lead_days = float((Z_FAIL - z_now) / slope)
        else:
            lead_days = float("inf")
        lead_days_capped = round(min(lead_days, 365.0), 1)

        turbine_rows.append({
            "turbine_id": tid, "health_score": round(health, 1), "status": status,
            "worst_component": worst_comp, "worst_signal": worst_sig,
            "anomaly_z": round(z_now, 2), "trend_z_per_day": round(slope, 4),
            "prognosis_lead_days": lead_days_capped if np.isfinite(lead_days) else None,
            "p_failure_now": round(p_now, 4),
            "rated_power_kw": C.RATED_POWER_KW,
        })

        # recent residual series (daily) for the incident drawer chart
        for sig in _COMP_SIGNALS[worst_comp]:
            d = _daily_z(recent, sig)
            for ts, z in d.items():
                series_rows.append({"turbine_id": tid, "signal": sig,
                                    "date": ts, "resid_z": round(float(z), 3)})

        if status in ("degrading", "critical"):
            # SHAP-style attribution: normalized positive severity per signal
            sev_all = {s: v for sd in comp_detail.values() for s, v in sd.items()}
            total = sum(v for v in sev_all.values() if v > 0) or 1.0
            attribution = sorted(
                ({"signal": s, "component": C.TEMP_TARGETS[s],
                  "severity_z": round(v, 3), "weight": round(v / total, 3)}
                 for s, v in sev_all.items() if v > 0.2),
                key=lambda r: -r["weight"])
            for p in pf_curve:
                prognosis_rows.append({"turbine_id": tid, **p})
            incidents.append({
                "turbine_id": tid, "component": worst_comp,
                "health_score": round(health, 1), "status": status,
                "anomaly_z": round(z_now, 2), "trend_z_per_day": round(slope, 4),
                "prognosis_lead_days": lead_days_capped if np.isfinite(lead_days) else None,
                "p_failure_now": round(p_now, 4),
                "p_failure_horizon": round(pf_curve[-1]["p_failure"], 4),
                "top_signal": worst_sig,
                "attribution": attribution,
                "detected_at": end.isoformat(),
            })

    th = pd.DataFrame(turbine_rows).sort_values("health_score").reset_index(drop=True)
    th.to_parquet(C.GOLD_DIR / "turbine_health.parquet")
    pd.DataFrame(prognosis_rows).to_parquet(C.GOLD_DIR / "prognosis_curves.parquet")
    pd.DataFrame(series_rows).to_parquet(C.GOLD_DIR / "residual_series.parquet")
    incidents.sort(key=lambda i: i["health_score"])
    (C.GOLD_DIR / "incidents.json").write_text(json.dumps(incidents, indent=2))

    print(f"  assessed {len(th)} turbines; {len(incidents)} incident(s): "
          + ", ".join(f"{i['turbine_id']}({i['component']},{i['status']},"
                      f"lead~{i['prognosis_lead_days']}d)" for i in incidents))
    return {"turbine_health": th, "incidents": incidents}


if __name__ == "__main__":
    assess()
