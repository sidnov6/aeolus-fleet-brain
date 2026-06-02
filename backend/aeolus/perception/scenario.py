"""Degradation scenario injection (LABELLED SYNTHETIC).

The real Kelmarsh 2016 SCADA is mostly healthy operation, which makes for a flat
prognosis demo. To exercise the closed loop end-to-end we overlay a *physically
plausible* degradation signature onto a small number of turbines over the most
recent weeks of the record:

  - a gradually overheating main bearing (rising temperature residual), and
  - a milder generator-bearing drift on a second turbine.

Only the underlying temperatures are augmented. The normality models are trained
ONLY on the earlier, untouched baseline period, so the residuals they produce in
the recent window — and therefore the health score, the prognosis lead-time and
the SHAP-style attribution — are all genuinely learned, not hard-coded.

Output: data/silver/scada_scenario.parquet, plus a manifest describing exactly
what was injected so the demo can state it honestly.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from aeolus import config as C

# turbine -> list of (temp_signal, ramp_degC_at_end, onset_days_before_end)
# Moderate, early-onset degradation: clearly detectable but with weeks of lead
# time, so the optimiser has real freedom to find a cheap, safe window (rather
# than being forced to act immediately).
INJECTIONS = {
    "KWF3": [("front_bearing_temp", 8.5, 100), ("rotor_bearing_temp", 5.5, 100)],
    "KWF5": [("gen_bearing_rear_temp", 5.0, 70)],
    # a couple more across the expanded fleet for a richer ops picture
    "KWF11": [("front_bearing_temp", 7.0, 90)],
    "KWF16": [("gen_bearing_front_temp", 6.0, 80), ("gen_bearing_rear_temp", 4.0, 80)],
}


def inject() -> pd.DataFrame:
    scada = pd.read_parquet(C.SILVER_DIR / "scada.parquet")
    scada["timestamp"] = pd.to_datetime(scada["timestamp"], utc=True)
    scada = scada.sort_values(["turbine_id", "timestamp"]).reset_index(drop=True)

    end = scada["timestamp"].max()
    manifest = {"end_of_record": end.isoformat(), "label": "SYNTHETIC", "injections": []}

    for tid, specs in INJECTIONS.items():
        mask_t = scada["turbine_id"] == tid
        ts = scada.loc[mask_t, "timestamp"]
        for sig, ramp, onset_days in specs:
            onset = end - pd.Timedelta(days=onset_days)
            within = mask_t & (scada["timestamp"] >= onset)
            # progress 0->1 across the degradation window, slightly super-linear
            frac = ((scada.loc[within, "timestamp"] - onset)
                    / (end - onset)).clip(0, 1).astype(float)
            bump = ramp * (frac ** 1.6)
            # only add heat while the machine is actually running (power > 50 kW)
            running = scada.loc[within, "power"].fillna(0) > 50.0
            add = np.where(running, bump, bump * 0.25)
            scada.loc[within, sig] = scada.loc[within, sig] + add
            manifest["injections"].append({
                "turbine_id": tid, "signal": sig,
                "ramp_degC": ramp, "onset": onset.isoformat(),
                "onset_days_before_end": onset_days,
            })

    out = C.SILVER_DIR / "scada_scenario.parquet"
    scada.to_parquet(out)
    (C.SILVER_DIR / "scenario_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  injected degradation (SYNTHETIC) into {list(INJECTIONS)} -> {out.name}")
    return scada


if __name__ == "__main__":
    inject()
