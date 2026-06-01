"""Perception model training: per-component normality regressors + power curve.

Normality model (the heart of SCADA condition monitoring): for each turbine and
each component temperature, learn the *expected* temperature given operating
conditions (power, rotor speed, wind, ambient). The residual

    residual = actual_temp - expected_temp

is the anomaly signal. A healthy machine sits near zero; a degrading component
runs hotter than conditions justify, so its residual climbs. Models are trained
ONLY on the early baseline window so later degradation shows up as drift.

Power curve: monotone wind->power lookup fitted on clean operating data, used by
the market layer to value lost generation.
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_squared_error

from aeolus import config as C

# fraction of each turbine's record treated as the assumed-normal training baseline
BASELINE_FRACTION = 0.55
_MODELS_PATH = C.ARTIFACT_DIR / "normality_models.pkl"
_PC_PATH = C.ARTIFACT_DIR / "power_curves.pkl"


def _operating(df: pd.DataFrame) -> pd.Series:
    """Rows where the turbine is genuinely generating (clean conditions)."""
    return (df["power"] > 50.0) & df[C.NORMALITY_DRIVERS].notna().all(axis=1)


def train_normality(scada: pd.DataFrame) -> dict:
    """Train one expected-temperature regressor per (turbine, temp_signal)."""
    models: dict = {}
    metrics = []
    for tid, df in scada.groupby("turbine_id"):
        df = df.sort_values("timestamp").reset_index(drop=True)
        cut = int(len(df) * BASELINE_FRACTION)
        baseline = df.iloc[:cut]
        op = baseline[_operating(baseline)]
        for sig in C.TEMP_TARGETS:
            sub = op[C.NORMALITY_DRIVERS + [sig]].dropna()
            if len(sub) < 500:
                continue
            X = sub[C.NORMALITY_DRIVERS].to_numpy()
            y = sub[sig].to_numpy()
            model = HistGradientBoostingRegressor(
                max_iter=140, max_depth=6, learning_rate=0.08,
                l2_regularization=1.0, random_state=0)
            model.fit(X, y)
            rmse = float(np.sqrt(mean_squared_error(y, model.predict(X))))
            resid = y - model.predict(X)
            models[(tid, sig)] = {
                "model": model,
                "resid_mean": float(resid.mean()),
                "resid_std": float(resid.std() + 1e-6),
                "rmse": rmse,
            }
            metrics.append({"turbine_id": tid, "signal": sig, "rmse_degC": round(rmse, 3),
                            "n_train": len(sub)})
    with open(_MODELS_PATH, "wb") as fh:
        pickle.dump(models, fh)
    mdf = pd.DataFrame(metrics)
    mdf.to_parquet(C.GOLD_DIR / "normality_rmse.parquet")
    print(f"  normality: {len(models)} models, mean baseline RMSE "
          f"{mdf['rmse_degC'].mean():.2f} °C")
    return models


def predict_residuals(scada: pd.DataFrame, models: dict | None = None) -> pd.DataFrame:
    """Append standardized residual columns ('<sig>_resid_z') for every row."""
    if models is None:
        with open(_MODELS_PATH, "rb") as fh:
            models = pickle.load(fh)
    out = []
    for tid, df in scada.groupby("turbine_id"):
        df = df.sort_values("timestamp").reset_index(drop=True).copy()
        drivers_ok = df[C.NORMALITY_DRIVERS].notna().all(axis=1)
        for sig in C.TEMP_TARGETS:
            col_z = f"{sig}_resid_z"
            df[col_z] = np.nan
            key = (tid, sig)
            if key not in models or sig not in df:
                continue
            m = models[key]
            valid = drivers_ok & df[sig].notna()
            if valid.sum() == 0:
                continue
            pred = m["model"].predict(df.loc[valid, C.NORMALITY_DRIVERS].to_numpy())
            resid = df.loc[valid, sig].to_numpy() - pred
            df.loc[valid, f"{sig}_resid"] = resid
            df.loc[valid, col_z] = (resid - m["resid_mean"]) / m["resid_std"]
        out.append(df)
    return pd.concat(out, ignore_index=True)


def train_power_curves(scada: pd.DataFrame) -> dict:
    """Monotone wind->power lookup per turbine (0.5 m/s bins, clean baseline)."""
    curves: dict = {}
    bins = np.arange(0, 26.5, 0.5)
    centers = (bins[:-1] + bins[1:]) / 2
    for tid, df in scada.groupby("turbine_id"):
        op = df[(df["power"].notna()) & (df["wind_speed"].notna()) & (df["power"] >= 0)]
        binned = pd.cut(op["wind_speed"], bins, labels=centers)
        med = op.groupby(binned, observed=False)["power"].median()
        curve = med.reindex(centers).interpolate().fillna(0.0)
        # enforce physical monotonicity up to rated, then cap at rated power
        vals = np.maximum.accumulate(curve.to_numpy())
        vals = np.clip(vals, 0, C.RATED_POWER_KW)
        curves[tid] = {"wind": centers.tolist(), "power_kw": vals.tolist()}
    with open(_PC_PATH, "wb") as fh:
        pickle.dump(curves, fh)
    print(f"  power curves: fitted for {len(curves)} turbines")
    return curves


def expected_power_kw(tid: str, wind_ms, curves: dict | None = None):
    """Look up expected power (kW) for a wind speed (scalar or array)."""
    if curves is None:
        with open(_PC_PATH, "rb") as fh:
            curves = pickle.load(fh)
    c = curves.get(tid) or next(iter(curves.values()))
    return np.interp(np.asarray(wind_ms, dtype=float), c["wind"], c["power_kw"])


def run() -> None:
    scada = pd.read_parquet(C.SILVER_DIR / "scada_scenario.parquet")
    train_normality(scada)
    train_power_curves(scada)


if __name__ == "__main__":
    run()
