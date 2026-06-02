"""Fleet expansion — derive additional turbines so the ops centre runs at scale.

The real Kelmarsh farm has 6 turbines (measured SCADA). To exercise the system
on a realistically-sized fleet, we DERIVE additional turbines from the real ones:
each derived turbine's SCADA is a real turbine's series with small per-signal
offsets/noise and its own coordinates. They are labelled `data_source='derived'`
in the asset registry so nothing mistakes them for measured data.

Crucially, the derived series flow through the *exact same* real pipeline —
normality models are trained on them, anomaly/prognosis runs on them, the market
layer values them against live weather/prices at their own coordinates. Only the
raw SCADA origin is synthetic; everything downstream is the same machinery.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aeolus import config as C

N_DERIVED = 14                      # 6 real + 14 derived = 20 turbines
SIGNAL_COLS = [c for c in C.SIGNAL_MAP if c not in ("timestamp",)]
TEMP_COLS = list(C.TEMP_TARGETS)

# spread derived turbines around the Kelmarsh site in a loose grid
_BASE_LAT, _BASE_LON = 52.401, -0.943


def _derived_meta(i: int) -> dict:
    row = i // 5
    col = i % 5
    return {
        "latitude": _BASE_LAT + 0.010 + row * 0.009 + (col % 2) * 0.0015,
        "longitude": _BASE_LON + 0.012 + col * 0.011,
    }


def run() -> None:
    scada = pd.read_parquet(C.SILVER_DIR / "scada.parquet")
    scada["timestamp"] = pd.to_datetime(scada["timestamp"], utc=True)
    turbines = pd.read_parquet(C.SILVER_DIR / "turbines.parquet")
    registry = pd.read_parquet(C.SILVER_DIR / "asset_registry.parquet")

    real_ids = sorted(turbines["turbine_id"].unique())
    if "data_source" not in turbines.columns:
        turbines["data_source"] = "measured"
        registry["data_source"] = "measured"

    new_scada, new_turbines, new_registry = [], [], []
    for k in range(N_DERIVED):
        tid = f"KWF{7 + k}"
        base_id = real_ids[k % len(real_ids)]
        rng = np.random.default_rng(1000 + k)
        meta = _derived_meta(k)

        # clone + perturb the base turbine's SCADA
        df = scada[scada["turbine_id"] == base_id].copy()
        df["turbine_id"] = tid
        for col in SIGNAL_COLS:
            if col not in df:
                continue
            if col in TEMP_COLS:                      # temps: small bias + noise
                bias = rng.uniform(-2.0, 2.0)
                df[col] = df[col] + bias + rng.normal(0, 0.6, len(df))
            elif col == "power":                      # power: gentle scale
                df[col] = (df[col] * rng.uniform(0.95, 1.04)).clip(upper=C.RATED_POWER_KW)
            elif col == "wind_speed":
                df[col] = (df[col] * rng.uniform(0.97, 1.05)).clip(lower=0)
        new_scada.append(df)

        # turbine + registry rows (labelled derived)
        base_t = turbines[turbines["turbine_id"] == base_id].iloc[0].to_dict()
        base_t.update({"turbine_id": tid, "turbine_name": f"Kelmarsh {7 + k}",
                       "latitude": meta["latitude"], "longitude": meta["longitude"],
                       "data_source": "derived"})
        new_turbines.append(base_t)

        reg_rows = registry[registry["turbine_id"] == base_id].copy()
        reg_rows["turbine_id"] = tid
        reg_rows["turbine_name"] = f"Kelmarsh {7 + k}"
        reg_rows["latitude"] = meta["latitude"]
        reg_rows["longitude"] = meta["longitude"]
        reg_rows["isa95_path"] = reg_rows["isa95_path"].str.replace(base_id, tid, regex=False)
        reg_rows["data_source"] = "derived"
        new_registry.append(reg_rows)

    scada_out = pd.concat([scada] + new_scada, ignore_index=True)
    scada_out.to_parquet(C.SILVER_DIR / "scada.parquet")
    turbines_out = pd.concat([turbines, pd.DataFrame(new_turbines)], ignore_index=True)
    turbines_out.to_parquet(C.SILVER_DIR / "turbines.parquet")
    registry_out = pd.concat([registry] + new_registry, ignore_index=True)
    registry_out.to_parquet(C.SILVER_DIR / "asset_registry.parquet")

    n = turbines_out.shape[0]
    print(f"  fleet expanded: {len(real_ids)} measured + {N_DERIVED} derived = {n} turbines")


if __name__ == "__main__":
    run()
